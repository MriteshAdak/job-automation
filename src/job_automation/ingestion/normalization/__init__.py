"""Normalization package public exports (INGEST-02).

Exposes DefaultNormalizer, ports, quarantine envelopes, and normalization helpers.
"""

from __future__ import annotations

from job_automation.ingestion.normalization.compensation import normalize_compensation
from job_automation.ingestion.normalization.dates import (
    normalize_observed_at,
    normalize_source_date,
)
from job_automation.ingestion.normalization.locations import normalize_locations
from job_automation.ingestion.normalization.models import (
    NormalizationResult,
    QuarantineHandoff,
)
from job_automation.ingestion.normalization.ports import (
    CaptureSinkProvenanceReader,
    InMemoryRawProvenanceReader,
    NormalizationOptions,
    RawProvenanceReader,
)
from job_automation.ingestion.normalization.provenance import build_field_provenance
from job_automation.ingestion.normalization.quarantine import build_quarantine_handoff
from job_automation.ingestion.normalization.service import DefaultNormalizer
from job_automation.ingestion.normalization.text import (
    clean_company,
    clean_description,
    clean_html_to_text,
    clean_title,
    clean_url,
)
from job_automation.ingestion.normalization.workplace import (
    normalize_employment_type,
    normalize_workplace,
)

__all__ = [
    "CaptureSinkProvenanceReader",
    "DefaultNormalizer",
    "InMemoryRawProvenanceReader",
    "NormalizationOptions",
    "NormalizationResult",
    "QuarantineHandoff",
    "RawProvenanceReader",
    "build_field_provenance",
    "build_quarantine_handoff",
    "clean_company",
    "clean_description",
    "clean_html_to_text",
    "clean_title",
    "clean_url",
    "normalize_compensation",
    "normalize_employment_type",
    "normalize_locations",
    "normalize_observed_at",
    "normalize_source_date",
    "normalize_workplace",
]

