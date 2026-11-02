"""Common normalization service implementing the Normalizer Protocol (INGEST-02).

Normalizes C05 SourceJobDraft instances into validated C06 NormalizedPosting instances,
or returns structured ValidationIssues and QuarantineHandoffs on failure.
"""

from __future__ import annotations

import copy
from typing import Any

from job_automation.contracts.errors import ValidationIssue
from job_automation.contracts.interfaces import Normalizer
from job_automation.contracts.postings import NormalizedPosting, SourceJobDraft
from job_automation.contracts.primitives import ContentHash
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
from job_automation.ingestion.normalization.text import (
    clean_company,
    clean_description,
    clean_title,
    clean_url,
)
from job_automation.ingestion.normalization.workplace import (
    normalize_employment_type,
    normalize_workplace,
)
from job_automation.sources.adapters.raw import RawCaptureSink, compute_content_hash


class DefaultNormalizer:
    """Production normalizer implementing the boundary Normalizer Protocol (C05 → C06)."""

    def __init__(
        self,
        raw_reader: RawProvenanceReader | RawCaptureSink | None = None,
        options: NormalizationOptions | None = None,
    ) -> None:
        if isinstance(raw_reader, RawCaptureSink):
            self.raw_reader: RawProvenanceReader = CaptureSinkProvenanceReader(raw_reader)
        elif raw_reader is not None:
            self.raw_reader = raw_reader
        else:
            self.raw_reader = InMemoryRawProvenanceReader()

        self.options = options or NormalizationOptions()

    def register_raw_payload(
        self,
        raw_reference: str,
        content_bytes: bytes,
        content_hash: str | None = None,
    ) -> None:
        """Register raw bytes and optional hash directly into the reader for testing."""
        if isinstance(self.raw_reader, InMemoryRawProvenanceReader):
            self.raw_reader.register(raw_reference, content_bytes, content_hash)
        else:
            # Wrap reader if needed
            new_reader = InMemoryRawProvenanceReader()
            new_reader.register(raw_reference, content_bytes, content_hash)
            self.raw_reader = new_reader

    def normalize(
        self,
        draft: SourceJobDraft,
    ) -> tuple[NormalizedPosting | None, list[ValidationIssue]]:
        """Normalize a C05 source draft into C06 NormalizedPosting or validation issues.

        Protocol conformance for job_automation.contracts.interfaces.Normalizer.
        """
        result = self.normalize_with_quarantine(draft)
        return result.posting, result.issues

    def normalize_with_quarantine(
        self,
        draft: SourceJobDraft,
        input_ref: str | None = None,
        record_index: int | None = None,
    ) -> NormalizationResult:
        """Normalize a draft, returning the posting, issues, and quarantine handoff if failed."""
        issues: list[ValidationIssue] = []

        # 1. Structural type check of draft
        if not isinstance(draft, SourceJobDraft):
            issues.append(
                ValidationIssue(
                    field_path="draft",
                    code="invalid_field_type",
                    message="Input must be an instance of SourceJobDraft",
                    severity="error",
                )
            )
            return NormalizationResult(
                posting=None,
                issues=issues,
                quarantine=build_quarantine_handoff(
                    draft=None,
                    issues=issues,
                    normalizer_version=self.options.normalizer_version,
                    input_ref=input_ref,
                    record_index=record_index,
                ),
            )

        # 2. Check mapping version compatibility
        mapping_version = draft.source_mapped_fields.get("mapping_version", "1.0")
        if mapping_version not in self.options.supported_mapping_versions:
            issues.append(
                ValidationIssue(
                    field_path="source_mapped_fields.mapping_version",
                    code="unsupported_mapping_version",
                    message=(
                        f"Source mapping version '{mapping_version}' is not supported by "
                        f"normalizer version '{self.options.normalizer_version}'"
                    ),
                    severity="error",
                )
            )
            return NormalizationResult(
                posting=None,
                issues=issues,
                quarantine=build_quarantine_handoff(
                    draft=draft,
                    issues=issues,
                    normalizer_version=self.options.normalizer_version,
                    input_ref=input_ref,
                    record_index=record_index,
                ),
            )

        # 3. Resolve raw bytes and verify raw_content_hash
        raw_content_hash: str | None = None
        raw_res = self.raw_reader.get_raw(draft.raw_reference)
        if raw_res is not None:
            raw_bytes, expected_hash = raw_res
            computed_hash = compute_content_hash(raw_bytes)
            if expected_hash and computed_hash != expected_hash:
                issues.append(
                    ValidationIssue(
                        field_path="raw_content_hash",
                        code="raw_hash_mismatch",
                        message=(
                            "Raw payload bytes do not match expected raw_content_hash integrity checksum"
                        ),
                        severity="error",
                    )
                )
            else:
                raw_content_hash = computed_hash
        else:
            issues.append(
                ValidationIssue(
                    field_path="raw_reference",
                    code="raw_reference_unresolved",
                    message=(
                        f"Raw reference '{draft.raw_reference}' could not be resolved by provenance reader"
                    ),
                    severity="error",
                )
            )

        # 4. Core text fields cleaning
        title, title_issues = clean_title(draft.source_mapped_fields.get("title"))
        issues.extend(title_issues)

        company, comp_issues = clean_company(
            draft.source_mapped_fields.get("company_name_hint")
            or draft.source_mapped_fields.get("company")
        )
        issues.extend(comp_issues)

        description_clean, desc_issues = clean_description(
            draft.source_mapped_fields.get("description")
            or draft.source_mapped_fields.get("text")
        )
        issues.extend(desc_issues)

        source_url, url_issues = clean_url(
            draft.source_mapped_fields.get("source_url"),
            field_name="source_url",
            required=True,
        )
        issues.extend(url_issues)

        app_url, app_url_issues = clean_url(
            draft.source_mapped_fields.get("application_url"),
            field_name="application_url",
            required=False,
        )
        issues.extend(app_url_issues)

        company_id_raw = draft.source_mapped_fields.get("company_id_hint") or draft.source_mapped_fields.get("company_id")
        company_id_hint = str(company_id_raw).strip() if company_id_raw and isinstance(company_id_raw, str) else None

        # 5. Dates
        source_published_at, pub_issues = normalize_source_date(
            draft.source_mapped_fields.get("source_published_raw"),
            field_name="source_published_at",
            declared_tz=self.options.default_timezone,
        )
        issues.extend(pub_issues)

        source_updated_at, upd_issues = normalize_source_date(
            draft.source_mapped_fields.get("source_updated_raw"),
            field_name="source_updated_at",
            declared_tz=self.options.default_timezone,
        )
        issues.extend(upd_issues)

        source_deadline_at, ddl_issues = normalize_source_date(
            draft.source_mapped_fields.get("source_deadline_raw"),
            field_name="source_deadline_at",
            declared_tz=self.options.default_timezone,
        )
        issues.extend(ddl_issues)

        observed_at, obs_issues = normalize_observed_at(draft.fetch_time)
        issues.extend(obs_issues)

        # 6. Locations
        locations, loc_issues = normalize_locations(
            draft.source_mapped_fields.get("locations_raw")
        )
        issues.extend(loc_issues)

        # 7. Workplace & Remote Restrictions
        restrictions_raw = (
            draft.source_mapped_fields.get("remote_eligibility_restrictions")
            or draft.source_mapped_fields.get("remote_restrictions")
        )
        workplace_type, remote_restrictions, wp_issues = normalize_workplace(
            draft.source_mapped_fields.get("workplace_type_raw"),
            restrictions_raw=restrictions_raw,
        )
        issues.extend(wp_issues)

        # 8. Employment type
        employment_type, emp_issues = normalize_employment_type(
            draft.source_mapped_fields.get("employment_type_raw")
        )
        issues.extend(emp_issues)

        # 9. Compensation
        compensation, compensation_issues = normalize_compensation(
            draft.source_mapped_fields.get("compensation_raw")
        )
        issues.extend(compensation_issues)

        # 10. Advert language
        lang_raw = draft.source_mapped_fields.get("advert_language") or draft.source_mapped_fields.get("language")
        advert_language = str(lang_raw).strip().lower() if lang_raw and isinstance(lang_raw, str) else None

        # 11. Check for fatal errors
        has_errors = any(iss.severity == "error" for iss in issues)
        if has_errors or raw_content_hash is None or title is None or company is None or description_clean is None or source_url is None:
            quarantine = build_quarantine_handoff(
                draft=draft,
                issues=issues,
                normalizer_version=self.options.normalizer_version,
                raw_content_hash=raw_content_hash,
                input_ref=input_ref,
                record_index=record_index,
            )
            return NormalizationResult(
                posting=None,
                issues=issues,
                quarantine=quarantine,
            )

        # 12. Build field provenance
        populated_dict = {
            "title": title,
            "company_name_hint": company,
            "description_clean": description_clean,
            "source_url": source_url,
            "application_url": app_url,
            "company_id_hint": company_id_hint,
            "locations": locations,
            "workplace_type": workplace_type,
            "remote_eligibility_restrictions": remote_restrictions,
            "employment_type": employment_type,
            "compensation": compensation,
            "advert_language": advert_language,
            "source_published_at": source_published_at,
            "source_updated_at": source_updated_at,
            "source_deadline_at": source_deadline_at,
            "observed_at": observed_at,
        }
        field_provenance = build_field_provenance(
            mapped_fields=draft.source_mapped_fields,
            populated_fields=populated_dict,
        )

        posting = NormalizedPosting(
            source_key=draft.source_key,
            normalizer_version=self.options.normalizer_version,
            raw_reference=draft.raw_reference,
            raw_content_hash=ContentHash(raw_content_hash),
            company_name_hint=company,
            company_id_hint=company_id_hint,
            title=title,
            description_clean=description_clean,
            source_url=source_url,
            application_url=app_url,
            locations=locations,
            workplace_type=workplace_type,
            remote_eligibility_restrictions=remote_restrictions,
            employment_type=employment_type,
            compensation=compensation,
            advert_language=advert_language,
            source_published_at=source_published_at,
            source_updated_at=source_updated_at,
            source_deadline_at=source_deadline_at,
            observed_at=observed_at,
            field_provenance=field_provenance,
        )

        return NormalizationResult(
            posting=posting,
            issues=issues,
            quarantine=None,
        )
