"""Field-level source mapping and traceability validation for CONTEXT-02 evidence chunks."""

from __future__ import annotations

import uuid
from typing import Sequence

from job_automation.context.chunk_errors import ChunkValidationError
from job_automation.contracts.evidence import CandidateEvidenceReference
from job_automation.contracts.evidence_chunks import (
    AncestorContext,
    ChunkSourceMapping,
    EvidenceChunk,
)
from job_automation.contracts.profile import CandidateFact, ProfileSnapshot


class ChunkTraceabilityValidator:
    """Constructs and verifies fine-grained field-level C08 source mappings."""

    @staticmethod
    def build_source_mappings(
        profile_version: str,
        primary_fact: CandidateFact,
        ancestors: Sequence[AncestorContext],
    ) -> list[ChunkSourceMapping]:
        """Construct exact source mappings linking all rendered assertions to approved fields."""
        mappings: list[ChunkSourceMapping] = []

        # 1. Primary fact assertions
        prim_ref = CandidateEvidenceReference(
            profile_version=profile_version,
            fact_id=primary_fact.fact_id,
        )

        mappings.append(
            ChunkSourceMapping(
                reference=prim_ref,
                field_path="title",
                exact_value=primary_fact.title,
                is_ancestor_context=False,
            )
        )

        if primary_fact.organization is not None:
            mappings.append(
                ChunkSourceMapping(
                    reference=prim_ref,
                    field_path="organization",
                    exact_value=primary_fact.organization,
                    is_ancestor_context=False,
                )
            )

        if primary_fact.start_date is not None:
            mappings.append(
                ChunkSourceMapping(
                    reference=prim_ref,
                    field_path="start_date",
                    exact_value=primary_fact.start_date.value,
                    is_ancestor_context=False,
                )
            )

        if primary_fact.end_date is not None:
            mappings.append(
                ChunkSourceMapping(
                    reference=prim_ref,
                    field_path="end_date",
                    exact_value=primary_fact.end_date.value,
                    is_ancestor_context=False,
                )
            )

        for idx, claim in enumerate(primary_fact.claims):
            mappings.append(
                ChunkSourceMapping(
                    reference=prim_ref,
                    field_path=f"claims[{idx}]",
                    list_index=idx,
                    exact_value=claim,
                    is_ancestor_context=False,
                )
            )

        for idx, skill in enumerate(primary_fact.skills):
            mappings.append(
                ChunkSourceMapping(
                    reference=prim_ref,
                    field_path=f"skills[{idx}]",
                    list_index=idx,
                    exact_value=skill,
                    is_ancestor_context=False,
                )
            )

        for idx, metric in enumerate(primary_fact.metrics):
            mappings.append(
                ChunkSourceMapping(
                    reference=prim_ref,
                    field_path=f"metrics[{idx}]",
                    list_index=idx,
                    exact_value=metric,
                    is_ancestor_context=False,
                )
            )

        mappings.append(
            ChunkSourceMapping(
                reference=prim_ref,
                field_path="provenance",
                exact_value=primary_fact.provenance,
                is_ancestor_context=False,
            )
        )

        # 2. Ancestor assertions
        for anc in ancestors:
            anc_ref = CandidateEvidenceReference(
                profile_version=profile_version,
                fact_id=anc.fact_id,
            )
            mappings.append(
                ChunkSourceMapping(
                    reference=anc_ref,
                    field_path="title",
                    exact_value=anc.title,
                    is_ancestor_context=True,
                )
            )
            if anc.organization is not None:
                mappings.append(
                    ChunkSourceMapping(
                        reference=anc_ref,
                        field_path="organization",
                        exact_value=anc.organization,
                        is_ancestor_context=True,
                    )
                )
            if anc.start_date is not None:
                mappings.append(
                    ChunkSourceMapping(
                        reference=anc_ref,
                        field_path="start_date",
                        exact_value=anc.start_date.value,
                        is_ancestor_context=True,
                    )
                )
            if anc.end_date is not None:
                mappings.append(
                    ChunkSourceMapping(
                        reference=anc_ref,
                        field_path="end_date",
                        exact_value=anc.end_date.value,
                        is_ancestor_context=True,
                    )
                )
            mappings.append(
                ChunkSourceMapping(
                    reference=anc_ref,
                    field_path="provenance",
                    exact_value=anc.provenance,
                    is_ancestor_context=True,
                )
            )

        return mappings

    @staticmethod
    def verify_chunk_traceability(chunk: EvidenceChunk, snapshot: ProfileSnapshot) -> None:
        """Verify that every source mapping in a chunk resolves to an exact field in the snapshot."""
        if chunk.profile_version != snapshot.profile_version:
            raise ChunkValidationError(
                f"Chunk profile version '{chunk.profile_version}' does not match snapshot version '{snapshot.profile_version}'",
                field_path="profile_version",
            )
        if chunk.candidate_id != snapshot.candidate_id:
            raise ChunkValidationError(
                f"Chunk candidate ID '{chunk.candidate_id}' does not match snapshot candidate ID '{snapshot.candidate_id}'",
                field_path="candidate_id",
            )

        fact_by_id = {f.fact_id: f for f in snapshot.evidence_records}

        for mapping in chunk.sources:
            ref = mapping.reference
            if ref.profile_version != snapshot.profile_version:
                raise ChunkValidationError(
                    f"Source mapping cites profile version '{ref.profile_version}', expected '{snapshot.profile_version}'",
                    field_path="sources",
                )
            if ref.fact_id not in fact_by_id:
                raise ChunkValidationError(
                    f"Cited fact '{ref.fact_id}' not found in approved snapshot",
                    field_path="sources",
                )

            fact = fact_by_id[ref.fact_id]
            path = mapping.field_path

            if path == "title":
                actual = fact.title
            elif path == "organization":
                actual = fact.organization
            elif path == "start_date":
                actual = fact.start_date.value if fact.start_date else None
            elif path == "end_date":
                actual = fact.end_date.value if fact.end_date else None
            elif path.startswith("claims["):
                idx = mapping.list_index
                if idx is None or idx >= len(fact.claims):
                    raise ChunkValidationError(f"Claims index '{idx}' out of bounds on fact '{ref.fact_id}'")
                actual = fact.claims[idx]
            elif path.startswith("skills["):
                idx = mapping.list_index
                if idx is None or idx >= len(fact.skills):
                    raise ChunkValidationError(f"Skills index '{idx}' out of bounds on fact '{ref.fact_id}'")
                actual = fact.skills[idx]
            elif path.startswith("metrics["):
                idx = mapping.list_index
                if idx is None or idx >= len(fact.metrics):
                    raise ChunkValidationError(f"Metrics index '{idx}' out of bounds on fact '{ref.fact_id}'")
                actual = fact.metrics[idx]
            elif path == "provenance":
                actual = fact.provenance
            else:
                raise ChunkValidationError(f"Unknown field_path '{path}' in source mapping")

            if mapping.exact_value != actual:
                raise ChunkValidationError(
                    f"Source mapping value mismatch for '{path}' on fact '{ref.fact_id}': expected approved '{actual}', got '{mapping.exact_value}'",
                    field_path="sources",
                )

