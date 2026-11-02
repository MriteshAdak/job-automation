"""Tests for SQLite persistence, attempt recording, and CAS commitments (GEN-04-S06)."""
from __future__ import annotations

import json
import uuid
import pytest

from job_automation.generation.input_records import compute_sha256_digest


def test_validation_persistence_and_reopen(setup_validation):
    env = setup_validation()
    res = env.validation_service.validate_content(env.request.request_id, env.draft)

    assert res.report is not None
    report_id = res.report.report_id

    # Reopen from repository
    reopened = env.engine.document_validations.reopen(report_id)
    assert reopened == res.report
    assert reopened.report_hash == res.report.report_hash

    # Lookup by request
    by_req = env.engine.document_validations.get_by_request(env.request.request_id)
    assert by_req == res.report


def test_corrupt_report_json_detected_on_reopen(setup_validation):
    env = setup_validation()
    res = env.validation_service.validate_content(env.request.request_id, env.draft)
    assert res.report is not None
    report_id = res.report.report_id

    # Tamper with stored report_hash in database
    env.engine.conn.execute(
        "UPDATE document_validation_attempts SET report_hash = 'sha256:tampered' WHERE attempt_id = ?",
        (str(report_id),),
    )

    with pytest.raises(ValueError, match="validation_report_corrupt"):
        env.engine.document_validations.reopen(report_id)


def test_tampered_fatal_count_detected_on_reopen(setup_validation):
    env = setup_validation()
    res = env.validation_service.validate_content(env.request.request_id, env.draft)
    assert res.report is not None
    report_id = res.report.report_id

    # Tamper with fatal_count in table
    env.engine.conn.execute(
        "UPDATE document_validation_attempts SET fatal_count = 99 WHERE attempt_id = ?",
        (str(report_id),),
    )

    with pytest.raises(ValueError, match="validation_report_corrupt"):
        env.engine.document_validations.reopen(report_id)


def test_idempotent_revalidation_reuses_committed_report(setup_validation):
    env = setup_validation()
    res1 = env.validation_service.validate_content(env.request.request_id, env.draft)
    assert res1.report is not None

    res2 = env.validation_service.validate_content(env.request.request_id, env.draft)
    assert res2.report is not None
    assert res2.report.report_id == res1.report.report_id

