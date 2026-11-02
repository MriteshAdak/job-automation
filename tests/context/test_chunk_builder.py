"""Tests for lossless chunk assembly, full-field fidelity, and size guards (CONTEXT-02-S03)."""

from __future__ import annotations

import uuid

import pytest

from job_automation.context.chunk_builder import ChunkBuilder
from job_automation.context.chunk_errors import ChunkCapacityError
from job_automation.context.chunk_preparation import PreparedChunkFact
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.evidence_chunks import (
    AncestorContext,
    ChunkingSettings,
)
from job_automation.contracts.primitives import PrecisionDate
from job_automation.contracts.profile import CandidateFact


class TestChunkBuilder:
    def test_title_only_fact_builds_valid_chunk(self) -> None:
        cid = uuid.uuid4()
        fid = uuid.uuid4()
        fact = CandidateFact(
            fact_id=fid,
            kind=EvidenceFactKind.EDUCATION,
            title="B.Sc. Informatik",
            organization="TU München",
            start_date=PrecisionDate(value="2016", precision="year"),
            end_date=PrecisionDate(value="2019", precision="year"),
            provenance="urkunde.pdf",
            allowed_uses=["cv", "assessment"],
        )
        prep = PreparedChunkFact(
            primary_fact=fact,
            ancestors=[],
            effective_allowed_uses=["cv", "assessment"],
            dependency_fingerprints={str(fid): "hash_dep_1"},
            contextual_limitations=[],
        )

        builder = ChunkBuilder()
        chunk = builder.build_chunk(
            candidate_id=cid,
            profile_version="v1",
            purpose="cv",
            prepared_fact=prep,
            settings=ChunkingSettings(),
        )

        assert chunk.primary_fact_id == fid
        assert chunk.title == "B.Sc. Informatik"
        assert chunk.organization == "TU München"
        assert chunk.skills == []
        assert chunk.claims == []
        assert chunk.metrics == []
        assert "B.Sc. Informatik" in chunk.retrieval_text
        assert "TU München" in chunk.retrieval_text
        assert "2016 to 2019" in chunk.retrieval_text

    def test_full_field_fidelity_qualifiers_negation_and_unicode(self) -> None:
        cid = uuid.uuid4()
        fid = uuid.uuid4()
        fact = CandidateFact(
            fact_id=fid,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Leitender Entwickler für Großsysteme & Cloud",
            organization="Müller & Söhne IT-Lösungen GmbH",
            start_date=PrecisionDate(value="2020-03", precision="month"),
            end_date=None,  # ongoing, null end date
            claims=[
                "Keine Ausfälle während der gesamten Migration (0% Downtime)",
                "Hat bewusst auf NoSQL verzichtet zugunsten von PostgreSQL",
                "Verantwortlich für Qualitätsprüfung und Code-Reviews",
            ],
            skills=["Python", "PostgreSQL", "Python"],  # intentional duplicate skill
            metrics=["Über 100.000 aktive Nutzer täglich", "p99 Latenz < 15ms"],
            provenance="arbeitszeugnis_mueller_2024.pdf",
            allowed_uses=["assessment", "cv", "cover_letter"],
        )
        prep = PreparedChunkFact(
            primary_fact=fact,
            ancestors=[],
            effective_allowed_uses=["assessment", "cv", "cover_letter"],
            dependency_fingerprints={str(fid): "dep_hash_full"},
            contextual_limitations=[],
        )

        builder = ChunkBuilder()
        chunk = builder.build_chunk(
            candidate_id=cid,
            profile_version="v1",
            purpose="assessment",
            prepared_fact=prep,
            settings=ChunkingSettings(),
        )

        # Verbatim field checks
        assert chunk.title == "Leitender Entwickler für Großsysteme & Cloud"
        assert chunk.organization == "Müller & Söhne IT-Lösungen GmbH"
        assert chunk.claims[0] == "Keine Ausfälle während der gesamten Migration (0% Downtime)"
        assert chunk.claims[1] == "Hat bewusst auf NoSQL verzichtet zugunsten von PostgreSQL"
        # Duplicate skill preserved in order
        assert chunk.skills == ["Python", "PostgreSQL", "Python"]
        assert chunk.metrics == ["Über 100.000 aktive Nutzer täglich", "p99 Latenz < 15ms"]
        assert chunk.provenance == "arbeitszeugnis_mueller_2024.pdf"

        # Check retrieval_text does NOT synthesize 'present' for null end date
        assert "present" not in chunk.retrieval_text.lower()
        assert "Start Date: 2020-03" in chunk.retrieval_text
        assert "Dates: 2020-03 to present" not in chunk.retrieval_text

    def test_distinct_facts_with_identical_text_have_distinct_identities(self) -> None:
        cid = uuid.uuid4()
        fid1 = uuid.uuid4()
        fid2 = uuid.uuid4()

        # Two separate roles with identical title, org, dates
        fact1 = CandidateFact(
            fact_id=fid1,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Senior Engineer",
            organization="Google",
            start_date=PrecisionDate(value="2020", precision="year"),
            provenance="ref1",
            allowed_uses=["cv"],
        )
        fact2 = CandidateFact(
            fact_id=fid2,
            kind=EvidenceFactKind.EMPLOYMENT,
            title="Senior Engineer",
            organization="Google",
            start_date=PrecisionDate(value="2020", precision="year"),
            provenance="ref2",
            allowed_uses=["cv"],
        )

        builder = ChunkBuilder()
        prep1 = PreparedChunkFact(fact1, [], ["cv"], {str(fid1): "h1"}, [])
        prep2 = PreparedChunkFact(fact2, [], ["cv"], {str(fid2): "h2"}, [])

        chunk1 = builder.build_chunk(cid, "v1", "cv", prep1, ChunkingSettings())
        chunk2 = builder.build_chunk(cid, "v1", "cv", prep2, ChunkingSettings())

        assert chunk1.chunk_id != chunk2.chunk_id
        assert chunk1.primary_fact_id != chunk2.primary_fact_id

    def test_max_chunk_chars_size_guard_overflow_raises_capacity_error(self) -> None:
        cid = uuid.uuid4()
        fid = uuid.uuid4()
        fact = CandidateFact(
            fact_id=fid,
            kind=EvidenceFactKind.PROJECT,
            title="Very Long Project Title That Will Overflow The Configured Guard",
            claims=["A" * 200],
            provenance="doc",
            allowed_uses=["assessment"],
        )
        prep = PreparedChunkFact(fact, [], ["assessment"], {str(fid): "h"}, [])

        # Configure guard to 50 chars
        settings = ChunkingSettings(max_chunk_chars=50)
        builder = ChunkBuilder()

        with pytest.raises(ChunkCapacityError) as exc_info:
            builder.build_chunk(cid, "v1", "assessment", prep, settings)

        assert "exceeds max_chunk_chars limit of 50" in str(exc_info.value)
        assert exc_info.value.details["max_chunk_chars"] == 50
        assert exc_info.value.details["actual_chars"] > 50

