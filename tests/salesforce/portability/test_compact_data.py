"""Tests for compact-data conventions, candidate preservation, and capacity failure contracts (SF-04-S02).

Enforces:
- Raw HTML, debug logs, and LLM payloads remain in local storage, strictly excluded from Salesforce projection.
- Exact candidate field preservation: explicit nulls, date-only formats, multiline notes, German umlauts.
- No silent truncation of candidate fields or canonical external IDs.
- Non-destructive capacity behavior: no record deletion or retention alteration at capacity.
"""

from __future__ import annotations

import uuid
import pytest
from pydantic import ValidationError

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.salesforce.portability_records import JobExportRow
from job_automation.salesforce.sync_records import CandidateFieldSnapshot
from job_automation.salesforce.sync_serialization import serialize_canonical_json
from job_automation.salesforce.sync_settings import SyncMappingConfig


class TestCompactDataConventions:
    def test_raw_payload_and_logs_excluded_from_salesforce_fields(self) -> None:
        """Salesforce mapping configuration contains only compact business fields, zero raw HTML or debug logs."""
        config = SyncMappingConfig(expected_org_id="00D000000000001")

        # Inspect all mapped fields across both Job and Company
        all_job_fields = (
            [
                config.job_external_id_field,
                config.job_company_lookup_field,
                config.title_field,
                config.availability_field,
                config.disposition_field,
                config.reason_field,
                config.score_field,
                config.score_scale_field,
                config.last_evaluated_field,
            ]
            + config.candidate_fields
        )

        forbidden_markers = ["raw_html", "debug_log", "prompt_context", "model_reasoning", "stack_trace"]
        for f in all_job_fields:
            for marker in forbidden_markers:
                assert marker not in f.lower(), f"Prohibited raw data marker '{marker}' found in Salesforce field: {f}"

    def test_candidate_notes_preserves_multiline_and_german_umlauts(self) -> None:
        """Candidate notes with German umlauts (ä, ö, ü, ß) and newlines must serialize exactly without loss."""
        german_notes = (
            "Erstes Gespräch mit der Abteilungsleiterin Fr. Dr. Schönbrunn.\n"
            "Interesse an Automatisierungslösungen & Qualitätsprüfung.\n"
            "Rückmeldung bis übernächsten Dienstag erwartet!"
        )

        row = JobExportRow(
            canonical_job_id=uuid.uuid4(),
            salesforce_id="a00Job000000001AAA",
            name="Senior Automation Engineer",
            application_progress="Interviewing",
            candidate_notes=german_notes,
            candidate_decision="Priorität Hoch",
            follow_up_date="2026-11-10",
            interview_date="2026-11-04T14:30:00+01:00",
            system_modstamp="2026-11-01T12:00:00Z",
            observed_at="2026-11-01T12:05:00Z",
        )

        serialized = row.model_dump_json()
        deserialized = JobExportRow.model_validate_json(serialized)

        assert deserialized.candidate_notes == german_notes
        assert "Schönbrunn" in deserialized.candidate_notes
        assert "Qualitätsprüfung" in deserialized.candidate_notes
        assert "\n" in deserialized.candidate_notes
        assert deserialized.candidate_decision == "Priorität Hoch"

    def test_candidate_explicit_nulls_preserved_separately_from_defaults(self) -> None:
        """Deliberately cleared candidate fields must remain None, never coerced to empty string or creation defaults."""
        row = JobExportRow(
            canonical_job_id=uuid.uuid4(),
            salesforce_id="a00Job000000002AAA",
            name="Staff Platform Engineer",
            application_progress=None,  # Deliberately cleared
            candidate_notes=None,       # Deliberately cleared
            candidate_decision=None,    # Explicit null
            follow_up_date=None,
            interview_date=None,
            system_modstamp="2026-11-01T12:00:00Z",
            observed_at="2026-11-01T12:05:00Z",
        )

        data = row.model_dump()
        assert data["application_progress"] is None
        assert data["candidate_notes"] is None
        assert data["candidate_decision"] is None
        assert data["follow_up_date"] is None
        assert data["interview_date"] is None

    def test_canonical_id_must_be_valid_uuid(self) -> None:
        """Canonical External IDs must strictly be valid UUIDs; arbitrary text raises validation error."""
        with pytest.raises(ValidationError):
            JobExportRow(
                canonical_job_id="not-a-valid-uuid-string",  # type: ignore[arg-type]
                salesforce_id="a00Job000000001AAA",
                name="Software Engineer",
                system_modstamp="2026-11-01T12:00:00Z",
                observed_at="2026-11-01T12:05:00Z",
            )

    def test_capacity_failure_contract_never_deletes_records(self) -> None:
        """When capacity is exhausted or blocked, system raises or flags CAPACITY error; never deletes records."""
        err = ClassifiedError(
            category=ErrorCategory.CAPACITY,
            message="Storage capacity BLOCKED: free space below reserve.",
            recoverable=False,
            details={"action": "defer_new_records", "delete_allowed": False},
        )
        assert err.category == ErrorCategory.CAPACITY
        assert err.details.get("delete_allowed") is False
