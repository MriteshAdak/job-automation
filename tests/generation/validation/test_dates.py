"""Tests for date validation, precision preservation, and calendar rules (GEN-04-S03)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from job_automation.contracts.evidence import CandidateEvidenceReference
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import CandidateFact


def test_invented_precision_in_date_claim_is_fatal(setup_validation):
    env = setup_validation()
    cand_fact = env.bundle.ordered_facts[0]

    # Let's find or create a date claim on the draft
    # cand_fact has start_date: PrecisionDate(year=2021, month=3)
    # If claim text adds day "2021-03-15" or rewrites as "März 2021", it must fail
    cand_ref = CandidateEvidenceReference(
        source_kind="candidate",
        profile_version=env.snapshot.profile_version,
        fact_id=cand_fact.fact_id,
    )

    new_claims = list(env.draft.claims)
    # Replace first candidate claim with date claim
    new_claims[0] = new_claims[0].model_copy(update={
        "evidence_reference": cand_ref,
        "source_field": "start_date",
        "source_index": None,
        "text": "März 2021",  # Altered from 2021-03!
    })

    bad_pv = list(env.draft.protected_values)
    bad_pv[0] = bad_pv[0].model_copy(update={
        "evidence_reference": cand_ref,
        "source_field": "start_date",
        "original_value": cand_fact.start_date,
    })

    bad_draft = env.draft.model_copy(update={"claims": new_claims, "protected_values": bad_pv})
    res = env.validation_service.validate_content(env.request.request_id, bad_draft)

    assert res.report is not None
    assert res.report.fatal_count > 0
    codes = [i.code for i in res.report.issues]
    assert "date_text_altered" in codes


def test_null_end_date_converted_to_present_is_fatal(setup_validation):
    env = setup_validation()
    # Find a fact with end_date=None, or test when end_date is None
    cand_fact = env.bundle.ordered_facts[0]
    cand_ref = CandidateEvidenceReference(
        source_kind="candidate",
        profile_version=env.snapshot.profile_version,
        fact_id=cand_fact.fact_id,
    )

    new_claims = list(env.draft.claims)
    new_claims[0] = new_claims[0].model_copy(update={
        "evidence_reference": cand_ref,
        "source_field": "end_date",
        "source_index": None,
        "text": "Present",  # Null end date rendered as Present!
    })

    bad_pv = list(env.draft.protected_values)
    bad_pv[0] = bad_pv[0].model_copy(update={
        "evidence_reference": cand_ref,
        "source_field": "end_date",
        "original_value": getattr(cand_fact, "end_date", None),
    })

    bad_draft = env.draft.model_copy(update={"claims": new_claims, "protected_values": bad_pv})
    res = env.validation_service.validate_content(env.request.request_id, bad_draft)

    assert res.report is not None
    assert res.report.fatal_count > 0
    codes = [i.code for i in res.report.issues]
    assert "null_date_converted" in codes


def test_invalid_calendar_date_is_fatal(setup_validation):
    # Feb 29 on non-leap year 2021 is invalid calendar date
    d_invalid = PrecisionDate(value="2021-02-29", precision="day")
    from job_automation.generation.validation_dates import validate_calendar_date
    assert validate_calendar_date(d_invalid) is False

    # Feb 29 on leap year 2020 is valid
    d_leap = PrecisionDate(value="2020-02-29", precision="day")
    assert validate_calendar_date(d_leap) is True

    # Feb 31 is invalid
    d_feb31 = PrecisionDate(value="2020-02-31", precision="day")
    assert validate_calendar_date(d_feb31) is False


def test_reversed_date_range_is_fatal(setup_validation):
    env = setup_validation()
    cand_fact = env.bundle.ordered_facts[0]
    cand_ref = CandidateEvidenceReference(
        source_kind="candidate",
        profile_version=env.snapshot.profile_version,
        fact_id=cand_fact.fact_id,
    )

    # If fact has start=2023-01 and end=2021-01, range is definitely reversed
    reversed_fact = cand_fact.model_copy(update={
        "start_date": PrecisionDate(value="2023-01", precision="month"),
        "end_date": PrecisionDate(value="2021-01", precision="month"),
    })

    # Put reversed fact into source map for validation
    source_map = {
        "claims": {
            "claim_start": {
                "subject": "candidate",
                "fact": reversed_fact,
                "field": "start_date",
                "selected_val": reversed_fact.start_date.value,
            }
        },
        "facts_by_id": {cand_fact.fact_id: reversed_fact},
    }

    # Verify validate_dates detects reversed range
    from job_automation.generation.validation_dates import validate_dates
    new_claims = [
        env.draft.claims[0].model_copy(update={
            "claim_id": "claim_start",
            "source_field": "start_date",
            "text": "2023-01",
            "evidence_reference": cand_ref,
        })
    ]
    test_draft = env.draft.model_copy(update={"claims": new_claims})
    issues = validate_dates(test_draft, source_map)

    codes = [i.code for i in issues]
    assert "reversed_date_range" in codes

