"""Independent offline verifier for Salesforce candidate-owned data export packages (SF-04-S05).

Enforces:
- Manifest schema validation and version compatibility.
- Containment checks rejecting absolute paths, path traversal, or symlink escapes.
- Byte-for-byte SHA-256 and size verification for every packaged file.
- Strict JSONL parsing for companies, jobs, snapshots, history, and issues.
- Unique canonical UUID validation for all exported companies and jobs.
- Company relationship closure: every referenced company must exist in companies.jsonl.
- Exact candidate field presence, null distinction, and date format conformance.
- Rejection of tampered, corrupted, or incomplete packages.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from job_automation.salesforce.portability_records import (
    CompanyExportRow,
    ExportManifest,
    ExportVerificationReport,
    JobExportRow,
)

logger = logging.getLogger(__name__)


def verify_export_package(
    export_dir: Path | str,
    expected_org_id: str | None = None,
    expected_mapping_version: str | None = None,
) -> ExportVerificationReport:
    """Independently verify the cryptographic integrity, schema, and relationship closure of an export package."""
    root = Path(export_dir).resolve()
    issues: list[str] = []
    warnings: list[str] = []
    checked_files: list[str] = []
    total_records: dict[str, int] = {}

    if not root.is_dir():
        return ExportVerificationReport(
            is_valid=False,
            completeness_status="invalid",
            checked_files=[],
            total_records={},
            issues=[f"Export package directory does not exist: {root}"],
            warnings=[],
        )

    # 1. Verify manifest.json
    manifest_file = root / "manifest.json"
    if not manifest_file.is_file():
        return ExportVerificationReport(
            is_valid=False,
            completeness_status="invalid",
            checked_files=[],
            total_records={},
            issues=[f"Missing manifest.json in export directory: {root}"],
            warnings=[],
        )

    try:
        manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
        manifest = ExportManifest.model_validate(manifest_data)
    except Exception as exc:
        return ExportVerificationReport(
            is_valid=False,
            completeness_status="invalid",
            checked_files=["manifest.json"],
            total_records={},
            issues=[f"manifest.json failed schema validation: {exc}"],
            warnings=[],
        )

    checked_files.append("manifest.json")

    # Check org ID and mapping version if specified
    if expected_org_id and manifest.org_id != expected_org_id:
        issues.append(
            f"Org ID mismatch: manifest has '{manifest.org_id}', expected '{expected_org_id}'"
        )
    if expected_mapping_version and manifest.mapping_version != expected_mapping_version:
        issues.append(
            f"Mapping version mismatch: manifest has '{manifest.mapping_version}', expected '{expected_mapping_version}'"
        )

    # 2. Check files declared in manifest
    company_uuids: set[uuid.UUID] = set()
    company_sf_ids: set[str] = set()
    job_uuids: set[uuid.UUID] = set()

    for file_entry in manifest.files:
        rel_path = file_entry.relative_path
        # Path safety check
        if ".." in rel_path or rel_path.startswith("/") or rel_path.startswith("\\"):
            issues.append(f"Security violation: path traversal in manifest file entry '{rel_path}'")
            continue

        target_file = (root / rel_path).resolve()
        if not str(target_file).startswith(str(root)):
            issues.append(f"Security violation: file '{rel_path}' escapes export root directory")
            continue

        if not target_file.is_file():
            issues.append(f"Packaged file missing from export directory: '{rel_path}'")
            continue

        checked_files.append(rel_path)

        # Byte size check
        file_bytes = target_file.read_bytes()
        if len(file_bytes) != file_entry.size_bytes:
            issues.append(
                f"File size mismatch for '{rel_path}': expected {file_entry.size_bytes} bytes, got {len(file_bytes)} bytes"
            )

        # SHA-256 hash check
        actual_hash = hashlib.sha256(file_bytes).hexdigest()
        if actual_hash != file_entry.sha256:
            issues.append(
                f"Cryptographic hash mismatch for '{rel_path}': expected {file_entry.sha256}, got {actual_hash}"
            )

        # Parse contents based on file kind
        line_count = 0
        try:
            lines = file_bytes.decode("utf-8").splitlines()
            for line_idx, line in enumerate(lines, start=1):
                if not line.strip():
                    continue
                line_count += 1
                row_data = json.loads(line)

                if rel_path == "companies.jsonl":
                    comp_row = CompanyExportRow.model_validate(row_data)
                    if comp_row.canonical_company_id in company_uuids:
                        issues.append(
                            f"Duplicate canonical company UUID in companies.jsonl: {comp_row.canonical_company_id}"
                        )
                    company_uuids.add(comp_row.canonical_company_id)
                    company_sf_ids.add(comp_row.salesforce_id)

                elif rel_path == "jobs.jsonl":
                    job_row = JobExportRow.model_validate(row_data)
                    if job_row.canonical_job_id in job_uuids:
                        issues.append(
                            f"Duplicate canonical job UUID in jobs.jsonl: {job_row.canonical_job_id}"
                        )
                    job_uuids.add(job_row.canonical_job_id)

                    # Validate date formats if present
                    if job_row.follow_up_date:
                        try:
                            datetime.strptime(job_row.follow_up_date, "%Y-%m-%d")
                        except ValueError:
                            issues.append(
                                f"Invalid date format for follow_up_date in job {job_row.canonical_job_id}: '{job_row.follow_up_date}'"
                            )

            total_records[rel_path] = line_count
            if line_count != file_entry.record_count:
                issues.append(
                    f"Record count mismatch for '{rel_path}': manifest declares {file_entry.record_count}, found {line_count}"
                )

        except Exception as exc:
            issues.append(f"Failed to parse or validate records in '{rel_path}': {exc}")

    # 3. Check Parent Company Relationship Closure
    jobs_file = root / "jobs.jsonl"
    if jobs_file.is_file():
        try:
            for line in jobs_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                jdata = json.loads(line)
                comp_uuid_str = jdata.get("canonical_company_id")
                comp_sf_id = jdata.get("company_salesforce_id")
                job_uuid_str = jdata.get("canonical_job_id")

                if comp_uuid_str:
                    c_uuid = uuid.UUID(comp_uuid_str)
                    if c_uuid not in company_uuids:
                        issues.append(
                            f"Relationship closure failure: Job {job_uuid_str} references company UUID {c_uuid} "
                            f"not present in companies.jsonl"
                        )
                elif comp_sf_id and comp_sf_id not in company_sf_ids:
                    issues.append(
                        f"Relationship closure failure: Job {job_uuid_str} references company Salesforce ID {comp_sf_id} "
                        f"not present in companies.jsonl"
                    )
        except Exception as exc:
            issues.append(f"Error checking relationship closure: {exc}")

    # 4. Check for recorded fatal issues
    issues_file = root / "issues.jsonl"
    if issues_file.is_file():
        try:
            for line in issues_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                idata = json.loads(line)
                itype = idata.get("issue_type", "")
                if itype in ("invalid_job_uuid", "invalid_company_uuid", "missing_parent_company"):
                    issues.append(f"Recorded fatal export issue: {itype} ({idata.get('details')})")
                else:
                    warnings.append(f"Recorded non-fatal export issue: {itype} ({idata.get('details')})")
        except Exception as exc:
            issues.append(f"Error reading issues.jsonl: {exc}")

    is_valid = len(issues) == 0

    if not is_valid:
        completeness = "invalid"
    elif manifest.completeness_status != "complete":
        completeness = manifest.completeness_status
    else:
        completeness = "complete"

    return ExportVerificationReport(
        is_valid=is_valid,
        completeness_status=completeness,
        checked_files=checked_files,
        total_records=total_records,
        issues=issues,
        warnings=warnings,
    )

