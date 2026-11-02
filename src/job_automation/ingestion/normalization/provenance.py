"""Field provenance tracking and source path preservation (INGEST-02).

Preserves traceability from normalized C06 fields back to original raw paths
and mapped candidate fields:
- Populates field_provenance for every populated output field.
- Carries forward adapter-supplied mapping provenance paths.
- Records observed_at traceability to draft fetch_time.
"""

from __future__ import annotations

from typing import Any

from job_automation.contracts.enums import EmploymentType, WorkplaceType


def build_field_provenance(
    mapped_fields: dict[str, Any],
    populated_fields: dict[str, Any],
) -> dict[str, str]:
    """Construct field provenance mapping from populated outputs to source paths."""
    mapping_prov: dict[str, str] = mapped_fields.get("provenance") or {}
    prov: dict[str, str] = {}

    # Core required fields
    if populated_fields.get("title"):
        prov["title"] = mapping_prov.get("title", "title")

    if populated_fields.get("company_name_hint"):
        prov["company_name_hint"] = mapping_prov.get(
            "company_name_hint",
            mapping_prov.get("company", "company"),
        )

    if populated_fields.get("description_clean"):
        prov["description_clean"] = mapping_prov.get(
            "description",
            mapping_prov.get("text", "description"),
        )

    if populated_fields.get("source_url"):
        prov["source_url"] = mapping_prov.get("source_url", "source_url")

    if populated_fields.get("application_url"):
        prov["application_url"] = mapping_prov.get("application_url", "application_url")

    if populated_fields.get("company_id_hint"):
        prov["company_id_hint"] = mapping_prov.get("company_id_hint", "company_id_hint")

    # Collections and enums
    if populated_fields.get("locations"):
        prov["locations"] = mapping_prov.get("locations_raw", "locations_raw")

    wp = populated_fields.get("workplace_type")
    if wp is not None and wp != WorkplaceType.UNKNOWN:
        prov["workplace_type"] = mapping_prov.get("workplace_type_raw", "workplace_type_raw")
    elif "workplace_type_raw" in mapped_fields and mapped_fields["workplace_type_raw"] is not None:
        prov["workplace_type"] = mapping_prov.get("workplace_type_raw", "workplace_type_raw")

    if populated_fields.get("remote_eligibility_restrictions"):
        prov["remote_eligibility_restrictions"] = mapping_prov.get(
            "remote_eligibility_restrictions",
            mapping_prov.get("remote_restrictions", "remote_restrictions"),
        )

    emp = populated_fields.get("employment_type")
    if emp is not None and emp != EmploymentType.UNKNOWN:
        prov["employment_type"] = mapping_prov.get("employment_type_raw", "employment_type_raw")
    elif "employment_type_raw" in mapped_fields and mapped_fields["employment_type_raw"] is not None:
        prov["employment_type"] = mapping_prov.get("employment_type_raw", "employment_type_raw")

    if populated_fields.get("compensation") is not None:
        prov["compensation"] = mapping_prov.get("compensation_raw", "compensation_raw")

    if populated_fields.get("advert_language"):
        prov["advert_language"] = mapping_prov.get(
            "advert_language",
            mapping_prov.get("language", "advert_language"),
        )

    # Source timestamps
    if populated_fields.get("source_published_at") is not None:
        prov["source_published_at"] = mapping_prov.get(
            "source_published_raw", "source_published_raw"
        )

    if populated_fields.get("source_updated_at") is not None:
        prov["source_updated_at"] = mapping_prov.get(
            "source_updated_raw", "source_updated_raw"
        )

    if populated_fields.get("source_deadline_at") is not None:
        prov["source_deadline_at"] = mapping_prov.get(
            "source_deadline_raw", "source_deadline_raw"
        )

    # Observation instant
    prov["observed_at"] = "fetch_time"

    return prov

