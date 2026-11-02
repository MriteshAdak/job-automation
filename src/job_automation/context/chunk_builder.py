"""Lossless evidence chunk assembly for CONTEXT-02."""

from __future__ import annotations

import uuid
from typing import Sequence

from job_automation.context.chunk_errors import ChunkCapacityError
from job_automation.context.chunk_identity import (
    compute_binding_fingerprint,
    compute_chunk_content_version,
    generate_chunk_id,
)
from job_automation.context.chunk_preparation import PreparedChunkFact
from job_automation.context.chunk_rendering import DefaultChunkRenderer
from job_automation.context.chunk_traceability import ChunkTraceabilityValidator
from job_automation.contracts.evidence_chunks import (
    ChunkingSettings,
    EvidenceChunk,
)


class ChunkBuilder:
    """Assembles individual EvidenceChunk records with exact source mappings and fingerprints."""

    def __init__(self, renderer: DefaultChunkRenderer | None = None) -> None:
        self.renderer = renderer or DefaultChunkRenderer()

    def build_chunk(
        self,
        candidate_id: uuid.UUID,
        profile_version: str,
        purpose: str,
        prepared_fact: PreparedChunkFact,
        settings: ChunkingSettings,
    ) -> EvidenceChunk:
        """Construct one lossless, version-bound EvidenceChunk."""
        fact = prepared_fact.primary_fact

        # 1. Render deterministic retrieval text
        retrieval_text = self.renderer.render(
            primary_fact=fact,
            ancestors=prepared_fact.ancestors,
        )

        # 2. Check size guard if configured
        if settings.max_chunk_chars is not None:
            char_count = len(retrieval_text)
            if char_count > settings.max_chunk_chars:
                raise ChunkCapacityError(
                    f"Rendered chunk for fact '{fact.fact_id}' ({char_count} chars) exceeds max_chunk_chars limit of {settings.max_chunk_chars}",
                    field_path="max_chunk_chars",
                    details={
                        "fact_id": str(fact.fact_id),
                        "actual_chars": char_count,
                        "max_chunk_chars": settings.max_chunk_chars,
                    },
                )

        # 3. Build fine-grained C08 source mappings
        sources = ChunkTraceabilityValidator.build_source_mappings(
            profile_version=profile_version,
            primary_fact=fact,
            ancestors=prepared_fact.ancestors,
        )

        # 4. Generate stable UUIDv5 chunk_id
        chunk_id = generate_chunk_id(
            identity_scheme_version=settings.identity_scheme_version,
            candidate_id=candidate_id,
            purpose=purpose,
            primary_fact_id=fact.fact_id,
            slot=settings.granularity,
        )

        # 5. Compute chunk_version content fingerprint (profile-version-independent)
        chunk_version = compute_chunk_content_version(
            settings=settings,
            primary_fact=fact,
            ancestors=prepared_fact.ancestors,
            retrieval_text=retrieval_text,
            effective_allowed_uses=prepared_fact.effective_allowed_uses,
            dependency_fingerprints=prepared_fact.dependency_fingerprints,
            contextual_limitations=prepared_fact.contextual_limitations,
            source_mappings=sources,
        )

        # 6. Compute exact snapshot-bound fingerprint
        binding_fingerprint = compute_binding_fingerprint(
            candidate_id=candidate_id,
            profile_version=profile_version,
            purpose=purpose,
            chunk_id=chunk_id,
            chunk_version=chunk_version,
            primary_fact_id=fact.fact_id,
            primary_kind=fact.kind.value,
            sources=sources,
            retrieval_text=retrieval_text,
        )

        return EvidenceChunk(
            chunk_id=chunk_id,
            chunk_version=chunk_version,
            candidate_id=candidate_id,
            profile_version=profile_version,
            purpose=purpose,
            primary_fact_id=fact.fact_id,
            primary_kind=fact.kind,
            parent_id=fact.parent_id,
            ancestor_context=prepared_fact.ancestors,
            title=fact.title,
            organization=fact.organization,
            start_date=fact.start_date,
            end_date=fact.end_date,
            skills=list(fact.skills),
            claims=list(fact.claims),
            metrics=list(fact.metrics),
            provenance=fact.provenance,
            primary_allowed_uses=list(fact.allowed_uses or []),
            effective_allowed_uses=prepared_fact.effective_allowed_uses,
            sources=sources,
            retrieval_text=retrieval_text,
            dependency_fingerprints=prepared_fact.dependency_fingerprints,
            contextual_limitations=prepared_fact.contextual_limitations,
            binding_fingerprint=binding_fingerprint,
        )

