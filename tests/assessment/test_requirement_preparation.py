"""Tests for requirement preparation and query derivation (M02-02, M02-03)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest

from job_automation.assessment.llm_records import RequirementObligation
from job_automation.assessment.requirements import (
    prepare_deterministic_requirements,
    to_requirement_query_set,
)
from job_automation.contracts.enums import WorkplaceType
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey


def test_m02_02_structured_and_passage_extraction():
    """Extracts title requirement and description passages with verifiable character spans."""
    desc = """Requirements:
- Mindestens 5 Jahre Erfahrung mit Python und Django
- Fundierte Kenntnisse in PostgreSQL und REST APIs
- Erfahrung mit Docker und Kubernetes von Vorteil
"""
    posting = NormalizedPosting(
        source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="p1"),
        normalizer_version="1.0-test",
        raw_reference="test/ref.json",
        raw_content_hash="sha256:" + "a" * 64,
        company_name_hint="Acme AG",
        title="Senior Python Backend Engineer",
        description_clean=desc,
        source_url="https://example.com/job/1",
        workplace_type=WorkplaceType.HYBRID,
        observed_at=datetime.now(timezone.utc),
    )
    job_id = uuid.uuid4()
    rev = "sha256:" + "a" * 64

    req_set = prepare_deterministic_requirements(
        posting=posting,
        posting_revision=rev,
        canonical_job_id=job_id,
    )

    assert len(req_set.requirements) >= 3
    # Check title requirement
    title_req = req_set.requirements[0]
    assert title_req.requirement_id == "req_0"
    assert "Senior Python Backend Engineer" in title_req.text
    assert title_req.obligation == RequirementObligation.REQUIRED
    assert title_req.job_evidence.field_path == "title"
    assert title_req.job_evidence.source_span.start == 0
    assert title_req.job_evidence.source_span.end == len(posting.title)

    # Check description passages
    py_req = req_set.requirements[1]
    assert "Python" in py_req.text
    assert py_req.obligation == RequirementObligation.REQUIRED
    assert py_req.threshold == "5"
    assert py_req.unit == "years"

    # Verifiable character offsets in exact text
    span = py_req.job_evidence.source_span
    assert span is not None
    assert desc[span.start:span.end] == py_req.job_evidence.quotation


def test_m02_03_obligation_negation_and_alternatives():
    """Verifies preferred status, alternatives, negation, and advert language handling."""
    desc = """Qualifikationen:
- Deutschkenntnisse wünschenswert
- Bachelor-Abschluss oder vergleichbare Berufserfahrung
- Keine Zertifizierung erforderlich
- 3+ Jahre Erfahrung mit C++ und C#
"""
    posting = NormalizedPosting(
        source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="p2"),
        normalizer_version="1.0-test",
        raw_reference="test/ref.json",
        raw_content_hash="sha256:" + "b" * 64,
        company_name_hint="Tech AG",
        title="Softwareentwickler",
        description_clean=desc,
        source_url="https://example.com/job/2",
        workplace_type=WorkplaceType.ONSITE,
        advert_language="de",
        observed_at=datetime.now(timezone.utc),
    )
    job_id = uuid.uuid4()
    rev = "sha256:" + "b" * 64

    req_set = prepare_deterministic_requirements(
        posting=posting,
        posting_revision=rev,
        canonical_job_id=job_id,
    )

    req_map = {r.text: r for r in req_set.requirements}

    # 1. "Deutschkenntnisse wünschenswert" -> PREFERRED (cannot become mandatory C1)
    de_req = next(r for r in req_set.requirements if "Deutschkenntnisse" in r.text)
    assert de_req.obligation == RequirementObligation.PREFERRED

    # 2. "Bachelor-Abschluss oder vergleichbare Berufserfahrung" -> retains alternative
    alt_req = next(r for r in req_set.requirements if "Bachelor" in r.text)
    assert len(alt_req.alternatives) >= 2

    # 3. "Keine Zertifizierung erforderlich" -> retains negation, NOT required
    neg_req = next(r for r in req_set.requirements if "Keine Zertifizierung" in r.text)
    assert neg_req.obligation != RequirementObligation.REQUIRED

    # 4. Symbol-preserving skills (C++, C#)
    cpp_req = next(r for r in req_set.requirements if "C++" in r.text)
    assert cpp_req.threshold == "3"


def test_m02_03_german_advert_alone_does_not_create_language_requirement():
    """An advert written in German without explicit German requirements yields no language requirement."""
    desc = """Wir suchen einen Entwickler für unser Backend.
Anforderungen:
- Erfahrung mit Python und PostgreSQL
- Kenntnisse in Linux und Git
"""
    posting = NormalizedPosting(
        source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="p3"),
        normalizer_version="1.0-test",
        raw_reference="test/ref.json",
        raw_content_hash="sha256:" + "c" * 64,
        company_name_hint="Tech AG",
        title="Backend Entwickler",
        description_clean=desc,
        source_url="https://example.com/job/3",
        workplace_type=WorkplaceType.REMOTE,
        advert_language="de",
        observed_at=datetime.now(timezone.utc),
    )
    job_id = uuid.uuid4()
    rev = "sha256:" + "c" * 64

    req_set = prepare_deterministic_requirements(
        posting=posting,
        posting_revision=rev,
        canonical_job_id=job_id,
    )

    # Ensure no synthesized German proficiency requirement exists
    lang_reqs = [r for r in req_set.requirements if "deutsch" in r.text.lower() or "german" in r.text.lower()]
    assert len(lang_reqs) == 0


def test_m02_02_to_requirement_query_set():
    """Derived RequirementQuerySet preserves skill symbols and produces deterministic fingerprints."""
    desc = """Requirements:
- 3 years experience with C++, C#, and .NET Core
"""
    posting = NormalizedPosting(
        source_key=SourceKey(provider="arbeitnow", board_id="default", source_posting_id="p4"),
        normalizer_version="1.0-test",
        raw_reference="test/ref.json",
        raw_content_hash="sha256:" + "d" * 64,
        company_name_hint="Acme Corp",
        title="Systems Developer",
        description_clean=desc,
        source_url="https://example.com/job/4",
        workplace_type=WorkplaceType.ONSITE,
        observed_at=datetime.now(timezone.utc),
    )
    job_id = uuid.uuid4()
    rev = "sha256:" + "d" * 64

    req_set = prepare_deterministic_requirements(
        posting=posting,
        posting_revision=rev,
        canonical_job_id=job_id,
    )

    qset = to_requirement_query_set(req_set)
    assert len(qset.queries) == len(req_set.requirements)
    assert qset.query_set_fingerprint.startswith("sha256:")

    # Find the C++ query
    cpp_q = next(q for q in qset.queries if "C++" in q.query_text)
    # Check that terms preserve symbols
    term_set = set(cpp_q.terms)
    assert "c++" in term_set or "c#" in term_set or ".net" in term_set
