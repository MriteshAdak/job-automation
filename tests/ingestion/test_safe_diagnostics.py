"""Tests for credential sanitization and safe diagnostics in errors and receipts (INGEST-01-S04)."""

import json
from datetime import datetime, timezone

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.ingestion.models import PageReceipt


def test_safe_error_diagnostics_no_secret_leak():
    # Verify ClassifiedError serialization does not embed un-sanitized secrets
    err = ClassifiedError.from_category(
        category=ErrorCategory.AUTHENTICATION,
        message="Authentication failed for endpoint",
        details={"code": "auth_denied", "source_key": "private_src"},
    )
    dump_str = err.model_dump_json()
    assert "auth_denied" in dump_str
    assert "Bearer" not in dump_str
    assert "password" not in dump_str


def test_page_receipt_sanitization():
    now = datetime.now(timezone.utc)
    receipt = PageReceipt(
        traversal_id="trav_safe",
        page_index=1,
        attempt_count=1,
        source_key="safe_src",
        scope_id="prov_board",
        adapter_name="test-v1",
        raw_response_refs=["raw://safe/ref"],
        raw_response_hashes=["sha256:" + "a" * 64],
        observed_posting_ids=["job_007"],
        fetch_time=now,
    )
    receipt_json = receipt.model_dump_json()
    parsed = json.loads(receipt_json)
    assert parsed["traversal_id"] == "trav_safe"
    assert "Authorization" not in receipt_json

