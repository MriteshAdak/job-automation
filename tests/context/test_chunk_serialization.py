"""Tests for canonical serialization and deserialization of chunk contracts (CONTEXT-02-S04)."""

from __future__ import annotations

import json
import uuid

import pytest

from job_automation.context.chunk_serialization import (
    deserialize_chunk_change_set_from_json,
    deserialize_chunk_set_from_json,
    serialize_chunk_change_set_to_json,
    serialize_chunk_set_to_json,
    serialize_chunk_to_json,
)
from job_automation.contracts.enums import EvidenceFactKind
from job_automation.contracts.evidence import CandidateEvidenceReference
from job_automation.contracts.evidence_chunks import (
    BindingTransition,
    ChunkChangeSet,
    ChunkSet,
    ChunkSourceMapping,
    EvidenceChunk,
)
from job_automation.contracts.primitives import PrecisionDate


def create_sample_chunk() -> EvidenceChunk:
    cid = uuid.uuid4()
    fid = uuid.uuid4()
    chid = uuid.uuid4()
    ref = CandidateEvidenceReference(profile_version="v1", fact_id=fid)

    return EvidenceChunk(
        chunk_id=chid,
        chunk_version="hash_v1",
        candidate_id=cid,
        profile_version="v1",
        purpose="assessment",
        primary_fact_id=fid,
        primary_kind=EvidenceFactKind.EMPLOYMENT,
        title="Entwickler für Hochverfügbarkeit & Skalierung",
        organization="Müller IT-Lösungen GmbH",
        start_date=PrecisionDate(value="2020-03", precision="month"),
        skills=["Python", "PostgreSQL"],
        claims=["Migration von Altsystemen ohne Ausfälle"],
        metrics=["Latenzsenkung um 35%"],
        provenance="zeugnis.pdf",
        primary_allowed_uses=["assessment", "cv"],
        effective_allowed_uses=["assessment"],
        sources=[
            ChunkSourceMapping(
                reference=ref,
                field_path="title",
                exact_value="Entwickler für Hochverfügbarkeit & Skalierung",
            )
        ],
        retrieval_text="[Evidence]\nKind: employment\nTitle: Entwickler für Hochverfügbarkeit & Skalierung",
        binding_fingerprint="bind_hash_123",
    )


class TestChunkSerialization:
    def test_chunk_serialization_and_unescaped_unicode(self) -> None:
        chunk = create_sample_chunk()
        serialized = serialize_chunk_to_json(chunk)

        # Check German umlauts are preserved unescaped
        assert "Müller IT-Lösungen GmbH" in serialized
        assert "Hochverfügbarkeit" in serialized
        assert "Ausfälle" in serialized

        # Round-trip back to model
        reloaded = EvidenceChunk.model_validate_json(serialized)
        assert reloaded == chunk

    def test_chunk_set_round_trip(self) -> None:
        chunk = create_sample_chunk()
        cset = ChunkSet(
            candidate_id=chunk.candidate_id,
            profile_version="v1",
            purpose="assessment",
            snapshot_fingerprint="snap_hash_1",
            settings_fingerprint="set_hash_1",
            chunks=[chunk],
            eligible_fact_ids=[chunk.primary_fact_id],
            coverage_fact_ids=[chunk.primary_fact_id],
            excluded_fact_count=2,
            warnings=["Warning: optional parent omitted"],
            manifest_fingerprint="man_hash_1",
        )

        serialized = serialize_chunk_set_to_json(cset)
        reloaded = deserialize_chunk_set_from_json(serialized)
        assert reloaded == cset

    def test_chunk_change_set_round_trip(self) -> None:
        cid = uuid.uuid4()
        ch_id = uuid.uuid4()
        change_set = ChunkChangeSet(
            candidate_id=cid,
            purpose="assessment",
            base_manifest_fingerprint="base_man_1",
            target_manifest_fingerprint="target_man_2",
            added_chunk_ids=[ch_id],
            removed_chunk_ids=[],
            content_changed_chunk_ids=[],
            rebound_unchanged_chunk_ids=[],
            binding_transitions=[
                BindingTransition(
                    chunk_id=ch_id,
                    old_binding=None,
                    new_binding="bind_new_1",
                    reason_code="added",
                )
            ],
            reasons=["added_1_chunks"],
            replacement_required=True,
        )

        serialized = serialize_chunk_change_set_to_json(change_set)
        reloaded = deserialize_chunk_change_set_from_json(serialized)
        assert reloaded == change_set

