"""Candidate-owned data export service for Salesforce Developer Org (SF-04-S04).

Enforces:
- Full keyset pagination without early termination on single-page LIMIT completion.
- Scoped query of Company__c and Job__c objects with explicitly selected columns including SystemModstamp.
- Validation and preservation of canonical External ID UUIDs.
- Strict preservation of parent-child Company relationships and closure verification.
- Preservation of all five candidate-owned fields with exact null vs missing distinction.
- UTF-8 JSONL streaming preservation of multi-line candidate notes and German characters.
- Collection of historical candidate snapshots from local storage.
- Safe query of field history tracking (or explicit omission recording).
- Atomic staging and publication of verifiable export packages.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import SalesforceGatewayV2
from job_automation.contracts.salesforce import QueryPageRequest
from job_automation.salesforce.portability_records import (
    CandidateSnapshotExportRow,
    CompanyExportRow,
    ExportFileEntry,
    ExportIssueRow,
    ExportManifest,
    FieldHistoryExportRow,
    JobExportRow,
)
from job_automation.salesforce.portability_settings import PortabilitySettings
from job_automation.salesforce.sync_serialization import serialize_canonical_json
from job_automation.salesforce.sync_settings import SyncMappingConfig
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class CandidateExportService:
    """Orchestrates candidate data export, relationship closure, and manifest generation."""

    def __init__(self, engine: StorageEngine) -> None:
        self.engine = engine

    def export_candidate_data(
        self,
        gateway: SalesforceGatewayV2,
        config: SyncMappingConfig,
        settings: PortabilitySettings,
        scan_id: str | None = None,
        metadata_digest: str = "",
    ) -> ExportManifest:
        """Execute a complete, scoped export of candidate-owned data and relationships."""
        start_time = datetime.now(timezone.utc)
        s_id = scan_id or f"scan-{start_time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        export_id = uuid.uuid4()

        # Compute mapping hash
        mapping_hash = hashlib.sha256(
            serialize_canonical_json(config.model_dump())
        ).hexdigest()

        # Staging path
        staging_root = Path(settings.staging_root).resolve() / f"staging_{export_id}"
        staging_root.mkdir(parents=True, exist_ok=True)

        companies_rows: list[CompanyExportRow] = []
        jobs_rows: list[JobExportRow] = []
        snapshots_rows: list[CandidateSnapshotExportRow] = []
        history_rows: list[FieldHistoryExportRow] = []
        issues: list[ExportIssueRow] = []
        omissions: list[str] = []
        missing_fields: list[str] = []
        source_tokens: dict[str, str] = {}

        expected_counts = {"companies": 0, "jobs": 0, "snapshots": 0}
        read_counts = {"companies": 0, "jobs": 0, "snapshots": 0}
        saved_counts = {"companies": 0, "jobs": 0, "snapshots": 0}
        skipped_counts = {"companies": 0, "jobs": 0, "snapshots": 0}
        error_counts = {"companies": 0, "jobs": 0, "snapshots": 0}

        try:
            # -------------------------------------------------------------
            # 1. Export Company__c parent rows
            # -------------------------------------------------------------
            company_sf_to_uuid: dict[str, uuid.UUID] = {}
            last_company_id: str | None = None
            company_pagination_done = False

            company_fields = [
                "Id",
                config.company_external_id_field,
                "Name",
                "Company_Name__c",
                "SystemModstamp",
            ]

            while not company_pagination_done:
                soql = f"SELECT {', '.join(company_fields)} FROM {config.company_object}"
                if last_company_id:
                    soql += f" WHERE Id > '{last_company_id}'"
                soql += f" ORDER BY Id ASC LIMIT {settings.batch_size}"

                res = gateway.query_page(QueryPageRequest(soql=soql))
                if res.is_failure or res.value is None:
                    err_msg = res.failure.error.message if res.failure else "Query failed"
                    issues.append(
                        ExportIssueRow(
                            issue_type="company_query_failed",
                            details={"soql": soql, "error": err_msg},
                        )
                    )
                    error_counts["companies"] += 1
                    break

                page_records = res.value.records
                read_counts["companies"] += len(page_records)

                for rec in page_records:
                    sf_id = rec.get("Id")
                    ext_id = rec.get(config.company_external_id_field)
                    last_company_id = sf_id

                    if not sf_id or not ext_id:
                        issues.append(
                            ExportIssueRow(
                                salesforce_id=sf_id,
                                issue_type="missing_company_id",
                                details={"record": rec},
                            )
                        )
                        skipped_counts["companies"] += 1
                        continue

                    try:
                        comp_uuid = uuid.UUID(str(ext_id))
                    except ValueError:
                        issues.append(
                            ExportIssueRow(
                                salesforce_id=sf_id,
                                issue_type="invalid_company_uuid",
                                details={"external_id_value": str(ext_id)},
                            )
                        )
                        error_counts["companies"] += 1
                        continue

                    company_sf_to_uuid[sf_id] = comp_uuid
                    modstamp = str(rec.get("SystemModstamp") or "")

                    row = CompanyExportRow(
                        canonical_company_id=comp_uuid,
                        salesforce_id=sf_id,
                        name=str(rec.get("Name") or ""),
                        company_name=rec.get("Company_Name__c"),
                        system_modstamp=modstamp,
                        observed_at=start_time,
                    )
                    companies_rows.append(row)
                    saved_counts["companies"] += 1

                if len(page_records) < settings.batch_size and not bool(res.value.next_records_url):
                    company_pagination_done = True
                elif len(page_records) == 0:
                    company_pagination_done = True

            # -------------------------------------------------------------
            # 2. Export Job__c candidate rows & relationships
            # -------------------------------------------------------------
            last_job_id: str | None = None
            job_pagination_done = False

            select_job_fields = [
                "Id",
                config.job_external_id_field,
                config.job_company_lookup_field,
                "Name",
                "Job_Title__c",
                "Availability__c",
                "Assessment_Disposition__c",
                "SystemModstamp",
            ]
            for cf in config.candidate_fields:
                if cf not in select_job_fields:
                    select_job_fields.append(cf)

            while not job_pagination_done:
                soql = f"SELECT {', '.join(select_job_fields)} FROM {config.job_object}"
                if last_job_id:
                    soql += f" WHERE Id > '{last_job_id}'"
                soql += f" ORDER BY Id ASC LIMIT {settings.batch_size}"

                res = gateway.query_page(QueryPageRequest(soql=soql))
                if res.is_failure or res.value is None:
                    err_msg = res.failure.error.message if res.failure else "Query failed"
                    issues.append(
                        ExportIssueRow(
                            issue_type="job_query_failed",
                            details={"soql": soql, "error": err_msg},
                        )
                    )
                    error_counts["jobs"] += 1
                    break

                page_records = res.value.records
                read_counts["jobs"] += len(page_records)

                for rec in page_records:
                    sf_id = rec.get("Id")
                    ext_id = rec.get(config.job_external_id_field)
                    last_job_id = sf_id

                    if not sf_id or not ext_id:
                        issues.append(
                            ExportIssueRow(
                                salesforce_id=sf_id,
                                issue_type="missing_job_id",
                                details={"record": rec},
                            )
                        )
                        skipped_counts["jobs"] += 1
                        continue

                    try:
                        job_uuid = uuid.UUID(str(ext_id))
                    except ValueError:
                        issues.append(
                            ExportIssueRow(
                                salesforce_id=sf_id,
                                issue_type="invalid_job_uuid",
                                details={"external_id_value": str(ext_id)},
                            )
                        )
                        error_counts["jobs"] += 1
                        continue

                    # Company relationship closure check
                    comp_sf_id = rec.get(config.job_company_lookup_field)
                    canonical_comp_uuid: uuid.UUID | None = None
                    if comp_sf_id:
                        canonical_comp_uuid = company_sf_to_uuid.get(comp_sf_id)
                        if canonical_comp_uuid is None and settings.require_company_closure:
                            issues.append(
                                ExportIssueRow(
                                    canonical_id=str(job_uuid),
                                    salesforce_id=sf_id,
                                    issue_type="missing_parent_company",
                                    details={
                                        "company_salesforce_id": comp_sf_id,
                                        "lookup_field": config.job_company_lookup_field,
                                    },
                                )
                            )
                            error_counts["jobs"] += 1

                    # Candidate fields with exact null distinction
                    for f in config.candidate_fields:
                        if f not in rec and f not in missing_fields:
                            missing_fields.append(f)

                    modstamp = str(rec.get("SystemModstamp") or "")
                    source_tokens[str(job_uuid)] = modstamp

                    row = JobExportRow(
                        canonical_job_id=job_uuid,
                        salesforce_id=sf_id,
                        canonical_company_id=canonical_comp_uuid,
                        company_salesforce_id=comp_sf_id,
                        name=str(rec.get("Name") or ""),
                        job_title=rec.get("Job_Title__c"),
                        application_progress=rec.get("Application_Progress__c"),
                        candidate_notes=rec.get("Candidate_Notes__c"),
                        candidate_decision=rec.get("Candidate_Decision__c"),
                        follow_up_date=rec.get("Follow_Up_Date__c"),
                        interview_date=rec.get("Interview_Date__c"),
                        availability=rec.get("Availability__c"),
                        assessment_disposition=rec.get("Assessment_Disposition__c"),
                        system_modstamp=modstamp,
                        observed_at=start_time,
                    )
                    jobs_rows.append(row)
                    saved_counts["jobs"] += 1

                if len(page_records) < settings.batch_size and not bool(res.value.next_records_url):
                    job_pagination_done = True
                elif len(page_records) == 0:
                    job_pagination_done = True

            # -------------------------------------------------------------
            # 3. Export Historical Candidate Snapshots from Storage
            # -------------------------------------------------------------
            cur = self.engine.conn.execute(
                """
                SELECT snapshot_id, org_id, canonical_job_id, remote_record_id,
                       mapping_version, snapshot_hash, candidate_fields_json,
                       source_modification_token, observed_at
                FROM candidate_snapshots
                WHERE org_id = ?
                ORDER BY canonical_job_id, observed_at ASC
                """,
                (config.expected_org_id,),
            )
            snapshot_db_rows = cur.fetchall()
            expected_counts["snapshots"] = len(snapshot_db_rows)
            read_counts["snapshots"] = len(snapshot_db_rows)

            for s_row in snapshot_db_rows:
                s_id_uuid = uuid.UUID(s_row["snapshot_id"])
                j_id_uuid = uuid.UUID(s_row["canonical_job_id"])
                c_fields = json.loads(s_row["candidate_fields_json"])

                snap_row = CandidateSnapshotExportRow(
                    snapshot_id=s_id_uuid,
                    canonical_job_id=j_id_uuid,
                    remote_record_id=s_row["remote_record_id"],
                    mapping_version=s_row["mapping_version"],
                    snapshot_hash=s_row["snapshot_hash"],
                    candidate_fields=c_fields,
                    source_modification_token=s_row["source_modification_token"] or "",
                    observed_at=datetime.fromisoformat(s_row["observed_at"]),
                )
                snapshots_rows.append(snap_row)
                saved_counts["snapshots"] += 1

            # -------------------------------------------------------------
            # 4. Attempt Field History Export (if enabled)
            # -------------------------------------------------------------
            if settings.export_field_history:
                hist_soql = (
                    "SELECT Id, ParentId, Field, CreatedDate, CreatedById, OldValue, NewValue "
                    "FROM Job__History ORDER BY CreatedDate ASC LIMIT 2000"
                )
                hist_res = gateway.query_page(QueryPageRequest(soql=hist_soql))
                if hist_res.is_success and hist_res.value:
                    for h_rec in hist_res.value.records:
                        parent_sf = h_rec.get("ParentId") or ""
                        h_id = h_rec.get("Id") or ""
                        # Resolve parent job UUID if possible
                        matching_job = next(
                            (j.canonical_job_id for j in jobs_rows if j.salesforce_id == parent_sf),
                            None,
                        )
                        c_date_raw = h_rec.get("CreatedDate") or start_time.isoformat()
                        c_date = datetime.fromisoformat(c_date_raw.replace("Z", "+00:00"))

                        history_rows.append(
                            FieldHistoryExportRow(
                                history_id=h_id,
                                canonical_job_id=matching_job,
                                salesforce_parent_id=parent_sf,
                                field_name=str(h_rec.get("Field") or ""),
                                created_at=c_date,
                                created_by_id=str(h_rec.get("CreatedById") or ""),
                                old_value=h_rec.get("OldValue"),
                                new_value=h_rec.get("NewValue"),
                            )
                        )
                else:
                    omissions.append("Job__History tracking is unavailable or not queryable on remote org.")
            else:
                omissions.append("Field history export skipped by policy.")

            # -------------------------------------------------------------
            # 5. Write JSONL export files to staging
            # -------------------------------------------------------------
            files_manifest: list[ExportFileEntry] = []

            # 5a. companies.jsonl
            comp_path = staging_root / "companies.jsonl"
            with comp_path.open("w", encoding="utf-8") as f:
                for crow in companies_rows:
                    f.write(json.dumps(crow.model_dump(mode="json"), ensure_ascii=False) + "\n")
            comp_bytes = comp_path.read_bytes()
            files_manifest.append(
                ExportFileEntry(
                    relative_path="companies.jsonl",
                    size_bytes=len(comp_bytes),
                    sha256=hashlib.sha256(comp_bytes).hexdigest(),
                    record_count=len(companies_rows),
                )
            )

            # 5b. jobs.jsonl
            jobs_path = staging_root / "jobs.jsonl"
            with jobs_path.open("w", encoding="utf-8") as f:
                for jrow in jobs_rows:
                    f.write(json.dumps(jrow.model_dump(mode="json"), ensure_ascii=False) + "\n")
            jobs_bytes = jobs_path.read_bytes()
            files_manifest.append(
                ExportFileEntry(
                    relative_path="jobs.jsonl",
                    size_bytes=len(jobs_bytes),
                    sha256=hashlib.sha256(jobs_bytes).hexdigest(),
                    record_count=len(jobs_rows),
                )
            )

            # 5c. snapshots.jsonl
            snaps_path = staging_root / "snapshots.jsonl"
            with snaps_path.open("w", encoding="utf-8") as f:
                for srow in snapshots_rows:
                    f.write(json.dumps(srow.model_dump(mode="json"), ensure_ascii=False) + "\n")
            snaps_bytes = snaps_path.read_bytes()
            files_manifest.append(
                ExportFileEntry(
                    relative_path="snapshots.jsonl",
                    size_bytes=len(snaps_bytes),
                    sha256=hashlib.sha256(snaps_bytes).hexdigest(),
                    record_count=len(snapshots_rows),
                )
            )

            # 5d. history.jsonl
            hist_path = staging_root / "history.jsonl"
            with hist_path.open("w", encoding="utf-8") as f:
                for hrow in history_rows:
                    f.write(json.dumps(hrow.model_dump(mode="json"), ensure_ascii=False) + "\n")
            hist_bytes = hist_path.read_bytes()
            files_manifest.append(
                ExportFileEntry(
                    relative_path="history.jsonl",
                    size_bytes=len(hist_bytes),
                    sha256=hashlib.sha256(hist_bytes).hexdigest(),
                    record_count=len(history_rows),
                )
            )

            # 5e. issues.jsonl (if any)
            if issues:
                issues_path = staging_root / "issues.jsonl"
                with issues_path.open("w", encoding="utf-8") as f:
                    for irow in issues:
                        f.write(json.dumps(irow.model_dump(mode="json"), ensure_ascii=False) + "\n")
                issues_bytes = issues_path.read_bytes()
                files_manifest.append(
                    ExportFileEntry(
                        relative_path="issues.jsonl",
                        size_bytes=len(issues_bytes),
                        sha256=hashlib.sha256(issues_bytes).hexdigest(),
                        record_count=len(issues),
                    )
                )

            # -------------------------------------------------------------
            # 6. Evaluate completeness status
            # -------------------------------------------------------------
            end_time = datetime.now(timezone.utc)
            expected_counts["jobs"] = saved_counts["jobs"] + error_counts["jobs"] + skipped_counts["jobs"]
            expected_counts["companies"] = saved_counts["companies"] + error_counts["companies"] + skipped_counts["companies"]
            fatal_issues = [
                i
                for i in issues
                if i.issue_type
                in (
                    "invalid_job_uuid",
                    "invalid_company_uuid",
                    "missing_parent_company",
                    "job_query_failed",
                    "company_query_failed",
                )
            ]

            if not company_pagination_done or not job_pagination_done:
                completeness = "partial"
                notes = "Pagination incomplete due to query failure or interruption."
            elif fatal_issues:
                completeness = "partial"
                notes = f"Export contains {len(fatal_issues)} fatal identity or relationship closure issues."
            elif missing_fields:
                completeness = "partial"
                notes = f"Required candidate fields missing from Salesforce schema: {', '.join(missing_fields)}"
            elif len(jobs_rows) == 0:
                completeness = "complete"
                notes = "Zero remote jobs in authorized scope; scan verified clean."
            else:
                completeness = "complete"
                notes = (
                    f"Complete candidate export: {len(jobs_rows)} jobs, {len(companies_rows)} companies, "
                    f"{len(snapshots_rows)} local snapshots."
                )

            manifest = ExportManifest(
                format_version="1.0",
                export_id=export_id,
                scan_id=s_id,
                org_id=config.expected_org_id,
                api_version="60.0",
                mapping_version=config.mapping_version,
                mapping_hash=mapping_hash,
                metadata_digest=metadata_digest,
                start_time=start_time,
                end_time=end_time,
                capture_scope="project_candidate_data",
                expected_counts=expected_counts,
                read_counts=read_counts,
                saved_counts=saved_counts,
                skipped_counts=skipped_counts,
                error_counts=error_counts,
                missing_fields=missing_fields,
                pagination_completed=company_pagination_done and job_pagination_done,
                completeness_status=completeness,
                omissions=omissions,
                files=files_manifest,
                source_tokens=source_tokens,
                notes=notes,
            )

            # 5f. manifest.json
            manifest_path = staging_root / "manifest.json"
            manifest_json = json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False)
            manifest_path.write_text(manifest_json, encoding="utf-8")

            # -------------------------------------------------------------
            # 7. Atomic commit to final export directory
            # -------------------------------------------------------------
            dest_root = Path(settings.export_root).resolve()
            dest_root.mkdir(parents=True, exist_ok=True)
            final_dir_name = f"export_{export_id}_{s_id}"
            final_export_dir = dest_root / final_dir_name

            shutil.move(str(staging_root), str(final_export_dir))
            logger.info("Export package committed to: %s", final_export_dir)

            return manifest

        except Exception as exc:
            if staging_root.exists():
                shutil.rmtree(str(staging_root), ignore_errors=True)
            raise
