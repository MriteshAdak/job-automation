"""Tests for canonical candidate projection serialization and content fingerprinting."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

from job_automation.context.records import PreparedProfileContext
from job_automation.context.serialization import (
    build_mandatory_context_strings,
    compute_content_fingerprint,
    serialize_candidate_fact,
    serialize_candidate_model_projection,
)
from job_automation.contracts.context import ChronologyReference
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.primitives import MoneyAmount, PrecisionDate
from job_automation.contracts.profile import CandidateEligibility, CandidateFact


def create_sample_prepared_context() -> PreparedProfileContext:
    cid = uuid.uuid4()
    f1 = uuid.uuid4()
    f2 = uuid.uuid4()

    fact1 = CandidateFact(
        fact_id=f1,
        kind=EvidenceFactKind.EMPLOYMENT,
        title="Softwareentwickler für Cloud-Systeme",
        organization="Müller & Söhne GmbH",
        start_date=PrecisionDate(value="2020-03", precision="month"),
        end_date=PrecisionDate(value="2023-08", precision="month"),
        skills=["Python", "PostgreSQL", "Docker"],
        claims=[
            "Entwicklung hochverfügbarer Microservices mit über 99.9% Uptime",
            "Leitung eines Teams von 5 Ingenieuren",
        ],
        metrics=[],
        provenance="arbeitszeugnis_2023.pdf",
        allowed_uses=["assessment", "cv"],
    )

    fact2 = CandidateFact(
        fact_id=f2,
        parent_id=f1,
        kind=EvidenceFactKind.PROJECT,
        title="Migration von Altsystemen",
        start_date=PrecisionDate(value="2021", precision="year"),
        skills=["Kubernetes", "Terraform"],
        claims=["Erfolgreiche Migration ohne Service-Unterbrechung"],
        provenance="projektbericht_2021.pdf",
        allowed_uses=["assessment", "cv"],
    )

    chrono = [
        ChronologyReference(
            profile_version="v1.0",
            fact_id=f1,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Softwareentwickler für Cloud-Systeme",
            start_date=PrecisionDate(value="2020-03", precision="month"),
            end_date=PrecisionDate(value="2023-08", precision="month"),
            reason="chronology_employment",
        )
    ]

    elig = CandidateEligibility(
        work_authorization_countries=["DE", "CH"],
        remote_eligible=True,
        min_salary=MoneyAmount(amount=Decimal("80000"), currency="EUR"),
    )

    return PreparedProfileContext(
        candidate_id=cid,
        profile_version="v1.0",
        purpose="assessment",
        inclusion_rule_version="v1",
        mandatory_policy_version="v1",
        eligible_facts=[fact1, fact2],
        eligible_fact_ids=[f1, f2],
        mandatory_facts=[fact1],
        mandatory_fact_ids=[f1],
        mandatory_reasons={str(f1): ["chronology_employment"]},
        chronology=chrono,
        explicit_eligibility=elig,
        eligibility_source="v1.0#explicit_eligibility",
        excluded_fact_count=0,
        warnings=[],
    )


class TestContextSerialization:
    def test_complete_fact_serialization(self) -> None:
        prepared = create_sample_prepared_context()
        fact = prepared.eligible_facts[0]

        serialized = serialize_candidate_fact(fact)

        assert serialized["fact_id"] == str(fact.fact_id)
        assert serialized["kind"] == "employment"
        assert serialized["title"] == "Softwareentwickler für Cloud-Systeme"
        assert serialized["organization"] == "Müller & Söhne GmbH"
        assert serialized["start_date"] == {"value": "2020-03", "precision": "month", "schema_version": "1.0"}
        assert serialized["end_date"] == {"value": "2023-08", "precision": "month", "schema_version": "1.0"}
        assert serialized["skills"] == ["Python", "PostgreSQL", "Docker"]
        assert len(serialized["claims"]) == 2
        assert serialized["provenance"] == "arbeitszeugnis_2023.pdf"
        assert serialized["allowed_uses"] == ["assessment", "cv"]

    def test_unicode_and_key_ordering_preservation(self) -> None:
        prepared = create_sample_prepared_context()

        json_str = serialize_candidate_model_projection(prepared)

        # Unicode characters (German umlauts) must remain unescaped
        assert "Müller & Söhne GmbH" in json_str
        assert "Softwareentwickler für Cloud-Systeme" in json_str

        # Round-trip parse
        data = json.loads(json_str)
        assert data["candidate_id"] == str(prepared.candidate_id)
        assert len(data["facts"]) == 2
        assert len(data["chronology_anchors"]) == 1

        # Keys are sorted deterministically
        top_keys = list(data.keys())
        assert top_keys == sorted(top_keys)

    def test_distinct_facts_with_identical_text_preserved(self) -> None:
        prepared = create_sample_prepared_context()
        f_dup1 = uuid.uuid4()
        f_dup2 = uuid.uuid4()

        fact_a = CandidateFact(
            fact_id=f_dup1,
            kind=EvidenceFactKind.SKILL,
            title="Identical Title",
            claims=["Identical claim text"],
            skills=["Python"],
            provenance="doc_a",
            allowed_uses=["assessment"],
        )
        fact_b = CandidateFact(
            fact_id=f_dup2,
            kind=EvidenceFactKind.SKILL,
            title="Identical Title",
            claims=["Identical claim text"],
            skills=["Python"],
            provenance="doc_b",
            allowed_uses=["assessment"],
        )

        prepared.eligible_facts.extend([fact_a, fact_b])
        json_str = serialize_candidate_model_projection(prepared)
        data = json.loads(json_str)

        fact_ids = [f["fact_id"] for f in data["facts"]]
        assert str(f_dup1) in fact_ids
        assert str(f_dup2) in fact_ids
        assert len(fact_ids) == 4

    def test_content_fingerprint_determinism_and_sensitivity(self) -> None:
        job_id = uuid.uuid4()
        candidate_json = '{"candidate_id": "123", "facts": []}'

        fp1 = compute_content_fingerprint(
            candidate_projection_json=candidate_json,
            canonical_job_id=job_id,
            posting_revision="rev-1",
            purpose="assessment",
            builder_version="v1",
            serialization_version="v1",
            instruction_text="Evaluate candidate.",
            requirements=["Req 1"],
        )

        fp2 = compute_content_fingerprint(
            candidate_projection_json=candidate_json,
            canonical_job_id=job_id,
            posting_revision="rev-1",
            purpose="assessment",
            builder_version="v1",
            serialization_version="v1",
            instruction_text="Evaluate candidate.",
            requirements=["Req 1"],
        )

        assert fp1 == fp2
        assert fp1.startswith("sha256:")

        # Changed revision changes fingerprint
        fp_diff_rev = compute_content_fingerprint(
            candidate_projection_json=candidate_json,
            canonical_job_id=job_id,
            posting_revision="rev-2",
            purpose="assessment",
            builder_version="v1",
            serialization_version="v1",
            instruction_text="Evaluate candidate.",
            requirements=["Req 1"],
        )
        assert fp_diff_rev != fp1

        # Changed instructions change fingerprint
        fp_diff_inst = compute_content_fingerprint(
            candidate_projection_json=candidate_json,
            canonical_job_id=job_id,
            posting_revision="rev-1",
            purpose="assessment",
            builder_version="v1",
            serialization_version="v1",
            instruction_text="Different instructions.",
            requirements=["Req 1"],
        )
        assert fp_diff_inst != fp1

    def test_build_mandatory_context_strings(self) -> None:
        prepared = create_sample_prepared_context()
        strings = build_mandatory_context_strings(prepared)

        assert any("Work authorization: CH, DE" in s for s in strings)
        assert any("Remote eligible: True" in s for s in strings)
        assert any("Minimum salary expectation: 80000 EUR" in s for s in strings)
        assert any("Chronology [2020-03 - 2023-08]: Softwareentwickler" in s for s in strings)
