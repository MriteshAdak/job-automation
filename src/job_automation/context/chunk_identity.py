"""Stable identity generation, version hashing, and canonical fingerprinting for evidence chunks."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Sequence

from job_automation.contracts.evidence_chunks import (
    AncestorContext,
    ChunkSourceMapping,
    ChunkingSettings,
    EvidenceChunk,
)
from job_automation.contracts.profile import CandidateFact, ProfileSnapshot

CHUNK_IDENTITY_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_DNS, "context.evidence.job-automation.local"
)


def _canonical_json(data: Any) -> str:
    """Serialize data into deterministic, sorted-key, UTF-8 unescaped JSON."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(data: Any) -> str:
    """Compute SHA-256 hex digest of canonical JSON."""
    canonical = _canonical_json(data)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def generate_chunk_id(
    identity_scheme_version: str,
    candidate_id: uuid.UUID,
    purpose: str,
    primary_fact_id: uuid.UUID,
    slot: str = "whole_fact",
) -> uuid.UUID:
    """Derive deterministic UUIDv5 chunk_id from stable identity keys.

    Key components:
    - identity_scheme_version
    - candidate_id
    - purpose
    - primary_fact_id
    - slot (e.g. 'whole_fact')

    Explicitly excluded: profile_version, claim text, dates, timestamps, list index.
    """
    key_str = f"{identity_scheme_version}:{str(candidate_id)}:{purpose}:{str(primary_fact_id)}:{slot}"
    return uuid.uuid5(CHUNK_IDENTITY_NAMESPACE, key_str)


def compute_fact_dependency_fingerprint(fact: CandidateFact) -> str:
    """Compute SHA-256 fingerprint over complete canonical fact values.

    Covers all fields including parent link, dates, claims, skills, metrics, provenance, allowed_uses.
    """
    data = {
        "fact_id": str(fact.fact_id),
        "parent_id": str(fact.parent_id) if fact.parent_id else None,
        "kind": fact.kind.value,
        "title": fact.title,
        "organization": fact.organization,
        "start_date": fact.start_date.model_dump(mode="json") if fact.start_date else None,
        "end_date": fact.end_date.model_dump(mode="json") if fact.end_date else None,
        "skills": list(fact.skills),
        "claims": list(fact.claims),
        "metrics": list(fact.metrics),
        "provenance": fact.provenance,
        "allowed_uses": sorted(list(fact.allowed_uses or [])),
    }
    return _sha256_hex(data)


def compute_chunk_content_version(
    settings: ChunkingSettings,
    primary_fact: CandidateFact,
    ancestors: Sequence[AncestorContext],
    retrieval_text: str,
    effective_allowed_uses: Sequence[str],
    dependency_fingerprints: dict[str, str],
    contextual_limitations: Sequence[str],
    source_mappings: Sequence[ChunkSourceMapping],
) -> str:
    """Compute chunk_version content fingerprint over canonical content projection.

    Explicitly excludes profile_version and timestamps so unchanged content
    retains its content version across profile releases.
    """
    ancestor_dicts = [
        {
            "fact_id": str(a.fact_id),
            "parent_id": str(a.parent_id) if a.parent_id else None,
            "kind": a.kind.value,
            "title": a.title,
            "organization": a.organization,
            "start_date": a.start_date.model_dump(mode="json") if a.start_date else None,
            "end_date": a.end_date.model_dump(mode="json") if a.end_date else None,
            "provenance": a.provenance,
            "allowed_uses": sorted(list(a.allowed_uses)),
        }
        for a in ancestors
    ]

    source_dicts = [
        {
            "fact_id": str(sm.reference.fact_id),
            "field_path": sm.field_path,
            "list_index": sm.list_index,
            "exact_value": sm.exact_value,
            "char_span": sm.char_span.model_dump(mode="json") if sm.char_span else None,
            "is_ancestor_context": sm.is_ancestor_context,
        }
        for sm in source_mappings
    ]

    projection = {
        "algorithm_version": settings.algorithm_version,
        "identity_scheme_version": settings.identity_scheme_version,
        "rendering_version": settings.rendering_version,
        "parent_policy_version": settings.parent_policy_version,
        "granularity": settings.granularity,
        "primary_fact_id": str(primary_fact.fact_id),
        "primary_kind": primary_fact.kind.value,
        "title": primary_fact.title,
        "organization": primary_fact.organization,
        "start_date": primary_fact.start_date.model_dump(mode="json") if primary_fact.start_date else None,
        "end_date": primary_fact.end_date.model_dump(mode="json") if primary_fact.end_date else None,
        "skills": list(primary_fact.skills),
        "claims": list(primary_fact.claims),
        "metrics": list(primary_fact.metrics),
        "provenance": primary_fact.provenance,
        "primary_allowed_uses": sorted(list(primary_fact.allowed_uses or [])),
        "effective_allowed_uses": sorted(list(effective_allowed_uses)),
        "parent_id": str(primary_fact.parent_id) if primary_fact.parent_id else None,
        "ancestors": ancestor_dicts,
        "retrieval_text": retrieval_text,
        "dependency_fingerprints": dependency_fingerprints,
        "contextual_limitations": list(contextual_limitations),
        "sources": source_dicts,
    }
    return _sha256_hex(projection)


def compute_binding_fingerprint(
    candidate_id: uuid.UUID,
    profile_version: str,
    purpose: str,
    chunk_id: uuid.UUID,
    chunk_version: str,
    primary_fact_id: uuid.UUID,
    primary_kind: str,
    sources: Sequence[ChunkSourceMapping],
    retrieval_text: str,
) -> str:
    """Compute binding_fingerprint binding the chunk to exact snapshot C08 references."""
    data = {
        "candidate_id": str(candidate_id),
        "profile_version": profile_version,
        "purpose": purpose,
        "chunk_id": str(chunk_id),
        "chunk_version": chunk_version,
        "primary_fact_id": str(primary_fact_id),
        "primary_kind": primary_kind,
        "sources": [s.model_dump(mode="json") for s in sources],
        "retrieval_text": retrieval_text,
    }
    return _sha256_hex(data)


def compute_snapshot_fingerprint(snapshot: ProfileSnapshot) -> str:
    """Compute deterministic SHA-256 digest of approved C01 snapshot evidence and eligibility."""
    sorted_facts = sorted(
        snapshot.evidence_records,
        key=lambda f: (
            0 if f.start_date else 1,
            -(int(f.start_date.value.split("-")[0])) if f.start_date else 0,
            str(f.fact_id),
        ),
    )
    fact_data = [
        {
            "fact_id": str(f.fact_id),
            "parent_id": str(f.parent_id) if f.parent_id else None,
            "kind": f.kind.value,
            "title": f.title,
            "organization": f.organization,
            "start_date": f.start_date.model_dump(mode="json") if f.start_date else None,
            "end_date": f.end_date.model_dump(mode="json") if f.end_date else None,
            "skills": list(f.skills),
            "claims": list(f.claims),
            "metrics": list(f.metrics),
            "provenance": f.provenance,
            "allowed_uses": sorted(list(f.allowed_uses or [])),
        }
        for f in sorted_facts
    ]
    data = {
        "candidate_id": str(snapshot.candidate_id),
        "profile_version": snapshot.profile_version,
        "explicit_eligibility": snapshot.explicit_eligibility.model_dump(mode="json"),
        "evidence_records": fact_data,
    }
    return _sha256_hex(data)


def compute_settings_fingerprint(settings: ChunkingSettings) -> str:
    """Compute SHA-256 digest of effective chunking settings."""
    data = {
        "algorithm_version": settings.algorithm_version,
        "identity_scheme_version": settings.identity_scheme_version,
        "rendering_version": settings.rendering_version,
        "parent_policy_version": settings.parent_policy_version,
        "granularity": settings.granularity,
        "max_chunk_chars": settings.max_chunk_chars,
        "strict_parents": settings.strict_parents,
        "size_unit": settings.size_unit,
        "overflow_behavior": settings.overflow_behavior,
    }
    return _sha256_hex(data)


def compute_manifest_fingerprint(
    candidate_id: uuid.UUID,
    profile_version: str,
    purpose: str,
    snapshot_fingerprint: str,
    inclusion_rule_version: str,
    chunking_version: str,
    settings_fingerprint: str,
    chunk_binding_fingerprints: Sequence[str],
    eligible_fact_ids: Sequence[uuid.UUID],
    coverage_fact_ids: Sequence[uuid.UUID],
    excluded_fact_count: int,
    warnings: Sequence[str],
) -> str:
    """Compute manifest_fingerprint covering the complete ChunkSet manifest."""
    data = {
        "candidate_id": str(candidate_id),
        "profile_version": profile_version,
        "purpose": purpose,
        "snapshot_fingerprint": snapshot_fingerprint,
        "inclusion_rule_version": inclusion_rule_version,
        "chunking_version": chunking_version,
        "settings_fingerprint": settings_fingerprint,
        "chunk_binding_fingerprints": list(chunk_binding_fingerprints),
        "eligible_fact_ids": [str(fid) for fid in eligible_fact_ids],
        "coverage_fact_ids": [str(fid) for fid in coverage_fact_ids],
        "excluded_fact_count": excluded_fact_count,
        "warnings": list(warnings),
    }
    return _sha256_hex(data)
