"""Tests for continuation token validation and cycle detection (SOURCE-02-S02)."""

from __future__ import annotations

import pytest

from job_automation.sources.adapters.continuation import (
    create_continuation,
    validate_continuation,
)


def test_create_and_validate_continuation_success() -> None:
    token = create_continuation(
        kind="local_record",
        value="51",
        source_key="manual_csv",
        scope_id="scope-v1:test",
        adapter_name="manual_csv",
        input_hash="sha256:" + "1" * 64,
        options_hash="sha256:" + "2" * 64,
    )

    issues = validate_continuation(
        token,
        expected_source_key="manual_csv",
        expected_scope_id="scope-v1:test",
        expected_adapter_name="manual_csv",
        expected_input_hash="sha256:" + "1" * 64,
        expected_options_hash="sha256:" + "2" * 64,
    )
    assert len(issues) == 0


def test_validate_continuation_source_and_scope_mismatch() -> None:
    token = create_continuation(
        kind="local_record",
        value="51",
        source_key="source_a",
        scope_id="scope_a",
        adapter_name="manual_csv",
    )

    issues = validate_continuation(
        token,
        expected_source_key="source_b",
        expected_scope_id="scope_b",
        expected_adapter_name="manual_csv",
    )
    assert len(issues) == 2
    codes = {i.code for i in issues}
    assert "continuation_source_mismatch" in codes
    assert "continuation_scope_mismatch" in codes


def test_validate_continuation_stale_input() -> None:
    token = create_continuation(
        kind="local_record",
        value="51",
        source_key="src",
        scope_id="scope",
        adapter_name="manual_csv",
        input_hash="sha256:" + "1" * 64,
    )

    issues = validate_continuation(
        token,
        expected_source_key="src",
        expected_scope_id="scope",
        expected_adapter_name="manual_csv",
        expected_input_hash="sha256:" + "9" * 64,  # Changed input
    )
    assert len(issues) == 1
    assert issues[0].code == "continuation_input_stale"


def test_validate_continuation_immediate_non_progress_loop() -> None:
    token_1 = create_continuation(
        kind="cursor",
        value="p2",
        source_key="src",
        scope_id="scope",
        adapter_name="adapter",
    )
    token_2 = create_continuation(
        kind="cursor",
        value="p2",  # Repeated identical token value
        source_key="src",
        scope_id="scope",
        adapter_name="adapter",
    )

    issues = validate_continuation(
        token_2,
        expected_source_key="src",
        expected_scope_id="scope",
        expected_adapter_name="adapter",
        prior_token=token_1,
    )
    assert len(issues) == 1
    assert issues[0].code == "continuation_non_progress_loop"

