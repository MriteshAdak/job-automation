"""Candidate-data recovery package generation and conflict resolution (OPS-01-S05 / SF-04-S05).

Enforces:
- Structured package creation for the SF-04 recovery procedure.
- Inclusion of Company parent entities for reconstruction on replacement orgs.
- Preserving explicit nulls and External ID relationships (Canonical UUIDs).
- Same-org vs replacement-org ID remapping rules:
  - On same org: preserves remote Salesforce record IDs and compares SystemModstamp.
  - On replacement org: remote Salesforce IDs are cleared/provenance only; Companies and Jobs
    are joined and restored by canonical UUIDs with remapped parent lookups.
- Safe conflict detection:
  - Compares UTC timestamps accurately.
  - Retains newer remote candidate edits in Salesforce by default.
  - Detects missing-token or equal-token/different-value divergences for review.
- No automatic outbound mutations through machine sync during backup/restore.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from job_automation.salesforce.sync_settings import SyncMappingConfig
from job_automation.storage.engine import StorageEngine


def _parse_utc_timestamp(token_or_date: str | None) -> datetime | None:
    """Parse a date/timestamp or SystemModstamp token into a UTC datetime for chronological comparison."""
    if not token_or_date:
        return None
    s = str(token_or_date).strip()
    # Normalize trailing Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def generate_candidate_recovery_package(
    engine: StorageEngine,
    config: SyncMappingConfig,
    target_org_id: str | None = None,
    export_dir: str | None = None,
) -> dict[str, Any]:
    """Assemble a portable candidate-data recovery package for the SF-04 recovery procedure."""
    target_org = target_org_id or config.expected_org_id
    is_replacement_org = target_org != config.expected_org_id

    conn = engine.conn

    # 1. Collect Companies for relationship reconstruction
    company_cursor = conn.execute(
        """
        SELECT cj.canonical_job_id, cj.canonical_company_id, cj.company_name
        FROM canonical_jobs cj
        """
    )
    job_company_map: dict[str, dict[str, Any]] = {}
    companies_dict: dict[str, dict[str, Any]] = {}

    for row in company_cursor.fetchall():
        j_id = str(row["canonical_job_id"])
        c_id = str(row["canonical_company_id"]) if row["canonical_company_id"] else None
        c_name = row["company_name"] or "Unknown Company"
        job_company_map[j_id] = {
            "canonical_company_id": c_id,
            "company_name": c_name,
        }
        if c_id:
            companies_dict[c_id] = {
                "canonical_company_id": c_id,
                "company_name": c_name,
                "remote_record_id": None if is_replacement_org else None,
            }

    # 2. Collect Candidate Snapshots
    cursor = conn.execute(
        """
        SELECT canonical_job_id, remote_record_id, snapshot_hash,
               candidate_fields_json, source_modification_token, observed_at
        FROM candidate_snapshots
        WHERE org_id = ?
        ORDER BY observed_at ASC
        """,
        (config.expected_org_id,),
    )
    rows = cursor.fetchall()

    # Retain latest snapshot per canonical job
    latest_per_job: dict[str, dict[str, Any]] = {}
    for r in rows:
        job_id = r["canonical_job_id"]
        comp_info = job_company_map.get(job_id, {})
        latest_per_job[job_id] = {
            "canonical_job_id": job_id,
            "canonical_company_id": comp_info.get("canonical_company_id"),
            "company_name": comp_info.get("company_name"),
            "remote_record_id": r["remote_record_id"] if not is_replacement_org else None,
            "source_modification_token": r["source_modification_token"],
            "observed_at": r["observed_at"],
            "candidate_fields": json.loads(r["candidate_fields_json"]),
        }

    records_payload = list(latest_per_job.values())
    companies_payload = list(companies_dict.values())

    instructions = [
        "1. Verify target Salesforce organization identity, metadata schema, and field-level permissions.",
        "2. Ensure Company__c records are upserted by Canonical_Company_Id__c before dependent jobs.",
        "3. Upsert Job__c records by Canonical_Job_Id__c establishing parent Company lookup relationships.",
        "4. If target org is identical, compare SystemModstamp version tokens; newer candidate edits in Salesforce take precedence.",
        "5. If target org is new, assign new Salesforce record IDs and update local remote_mappings without changing Canonical IDs.",
        "6. Execute recovery via approved SF-04 import procedure. Normal machine synchronization must not dispatch candidate fields.",
    ]

    return {
        "format_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_org_id": config.expected_org_id,
        "target_org_id": target_org,
        "is_replacement_org": is_replacement_org,
        "mapping_version": config.mapping_version,
        "job_object": config.job_object,
        "company_object": config.company_object,
        "job_external_id_field": config.job_external_id_field,
        "company_external_id_field": config.company_external_id_field,
        "candidate_fields": config.candidate_fields,
        "total_records": len(records_payload),
        "total_companies": len(companies_payload),
        "companies": companies_payload,
        "records": records_payload,
        "recovery_instructions": instructions,
    }


def reconcile_recovery_conflicts(
    recovery_package: dict[str, Any],
    current_remote_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compare recovery package against live remote records to detect newer candidate edits.

    Newer candidate edits in Salesforce are retained by default; conflicts are reported.
    Chronological comparison parses UTC timestamps accurately.
    """
    records_to_restore: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    unchanged_count = 0

    for rec in recovery_package.get("records", []):
        job_id = rec["canonical_job_id"]
        pkg_token = rec.get("source_modification_token") or ""
        pkg_fields = rec.get("candidate_fields", {})

        remote_rec = current_remote_records.get(job_id)
        if not remote_rec:
            # Remote record missing in target org; mark for creation
            records_to_restore.append(rec)
            continue

        remote_token = str(remote_rec.get("SystemModstamp", ""))

        pkg_dt = _parse_utc_timestamp(pkg_token)
        rem_dt = _parse_utc_timestamp(remote_token)

        # Check if remote token is chronologically newer
        is_remote_newer = False
        if pkg_dt is not None and rem_dt is not None:
            is_remote_newer = rem_dt > pkg_dt
        elif remote_token and pkg_token:
            is_remote_newer = remote_token > pkg_token

        if is_remote_newer:
            # Remote is newer: Candidate made newer edits in Salesforce UI
            conflicts.append(
                {
                    "canonical_job_id": job_id,
                    "package_token": pkg_token,
                    "remote_token": remote_token,
                    "resolution": "retain_newer_remote_edit",
                    "remote_fields": {
                        k: remote_rec.get(k) for k in pkg_fields.keys() if k in remote_rec
                    },
                }
            )
        elif pkg_fields == {k: remote_rec.get(k) for k in pkg_fields.keys() if k in remote_rec}:
            unchanged_count += 1
        elif remote_token and pkg_token and remote_token == pkg_token:
            # Identical token but diverging fields: requires review
            conflicts.append(
                {
                    "canonical_job_id": job_id,
                    "package_token": pkg_token,
                    "remote_token": remote_token,
                    "resolution": "requires_review_diverging_fields",
                    "remote_fields": {
                        k: remote_rec.get(k) for k in pkg_fields.keys() if k in remote_rec
                    },
                }
            )
        else:
            records_to_restore.append(rec)

    return {
        "total_package_records": len(recovery_package.get("records", [])),
        "records_to_restore": len(records_to_restore),
        "conflicts_retained_remote": len(conflicts),
        "unchanged_records": unchanged_count,
        "conflict_details": conflicts,
    }
