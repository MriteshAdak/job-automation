"""SYNC-01 candidate-owned field preservation and local backup service (SYNC-01-S05).

Enforces:
- Reading candidate-owned fields (status, notes, decisions, follow-ups) from Salesforce
- Committing validated local snapshots in candidate_snapshots table before updates
- Bounded backup scans with resumable checkpoints
- Strict exclusion of candidate-owned fields from outbound writes and ordinary logs
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from job_automation.contracts.errors import ClassifiedError
from job_automation.contracts.interfaces import SalesforceGatewayV2
from job_automation.contracts.salesforce import (
    GetRecordRequest,
    QueryPageRequest,
)
from job_automation.salesforce.sync_ports import CandidateBackupPort
from job_automation.salesforce.sync_records import (
    CandidateBackupResult,
    CandidateFieldSnapshot,
)
from job_automation.salesforce.sync_serialization import serialize_canonical_json
from job_automation.salesforce.sync_settings import SyncMappingConfig

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine


class CandidateBackupService(CandidateBackupPort):
    """Production implementation of CandidateBackupPort."""

    def __init__(self, engine: StorageEngine) -> None:
        self.engine = engine

    def read_and_snapshot_candidate_fields(
        self,
        canonical_job_id: uuid.UUID,
        remote_record_id: str,
        gateway: SalesforceGatewayV2,
        config: SyncMappingConfig,
    ) -> CandidateFieldSnapshot | None:
        """Read candidate-owned fields for a tracked job and commit a snapshot."""
        if not config.candidate_fields:
            return None

        # Include SystemModstamp to track remote modification version
        fields_to_read = list(config.candidate_fields)
        if "SystemModstamp" not in fields_to_read:
            fields_to_read.append("SystemModstamp")
        req = GetRecordRequest(
            object_name=config.job_object,
            record_id=remote_record_id,
            fields=fields_to_read,
        )

        res = gateway.get_record(req)
        if res.is_failure or res.value is None:
            # Preserve last good snapshot on read failure without failing caller
            return None

        record_fields = res.value.fields
        # Filter down strictly to candidate fields
        extracted: dict[str, Any] = {}
        for f in config.candidate_fields:
            if f in record_fields:
                extracted[f] = record_fields[f]

        snapshot_hash = hashlib.sha256(serialize_canonical_json(extracted)).hexdigest()
        now_dt = datetime.now(timezone.utc)

        snapshot = CandidateFieldSnapshot(
            snapshot_id=uuid.uuid4(),
            org_id=config.expected_org_id,
            canonical_job_id=canonical_job_id,
            remote_record_id=remote_record_id,
            mapping_version=config.mapping_version,
            snapshot_hash=snapshot_hash,
            candidate_fields=extracted,
            source_modification_token=str(record_fields.get("SystemModstamp", "")),
            observed_at=now_dt,
            created_at=now_dt,
        )

        self.engine.candidate_snapshots.save_snapshot(snapshot)
        return snapshot

    def backup_candidate_fields(
        self,
        gateway: SalesforceGatewayV2,
        config: SyncMappingConfig,
        batch_size: int = 50,
    ) -> CandidateBackupResult:
        """Execute a bounded backup scan across all tracked jobs."""
        if not config.candidate_fields:
            return CandidateBackupResult(records_read=0, snapshots_saved=0, is_complete=True)

        checkpoint_id = f"backup-{config.expected_org_id}-{datetime.now(timezone.utc).strftime('%Y%m%d')}"
        last_cp = self.engine.candidate_snapshots.get_latest_checkpoint(config.expected_org_id)
        last_key = last_cp["last_processed_key"] if last_cp and not last_cp["is_complete"] else None

        # Build SOQL query with explicit SystemModstamp
        select_fields = ["Id", config.job_external_id_field, "SystemModstamp"]
        for f in config.candidate_fields:
            if f not in select_fields:
                select_fields.append(f)
        soql = f"SELECT {', '.join(select_fields)} FROM {config.job_object}"
        if last_key:
            soql += f" WHERE Id > '{last_key}'"
        soql += f" ORDER BY Id ASC LIMIT {batch_size}"

        query_req = QueryPageRequest(
            soql=soql,
        )

        query_res = gateway.query_page(query_req)
        if query_res.is_failure or query_res.value is None:
            errors = [query_res.failure.error] if query_res.failure else []
            self.engine.candidate_snapshots.save_checkpoint(
                checkpoint_id=checkpoint_id,
                org_id=config.expected_org_id,
                last_processed_key=last_key,
                is_complete=False,
                records_processed=0,
            )
            return CandidateBackupResult(
                records_read=0,
                snapshots_saved=0,
                is_complete=False,
                errors=errors,
            )

        records = query_res.value.records
        records_read = len(records)
        snapshots_saved = 0
        highest_id = last_key
        errors: list[ClassifiedError] = []

        for rec in records:
            sf_id = rec.get("Id")
            ext_id = rec.get(config.job_external_id_field)
            if not sf_id or not ext_id:
                errors.append(
                    ClassifiedError.validation(
                        f"Record '{sf_id or 'unknown'}' missing Id or External ID '{config.job_external_id_field}'"
                    )
                )
                continue

            highest_id = sf_id
            try:
                job_uuid = uuid.UUID(str(ext_id))
            except ValueError:
                errors.append(
                    ClassifiedError.validation(
                        f"Record '{sf_id}' contains invalid UUID external ID: '{ext_id}'"
                    )
                )
                continue

            extracted: dict[str, Any] = {}
            for f in config.candidate_fields:
                if f in rec:
                    extracted[f] = rec[f]

            snapshot_hash = hashlib.sha256(serialize_canonical_json(extracted)).hexdigest()
            now_dt = datetime.now(timezone.utc)

            snapshot = CandidateFieldSnapshot(
                snapshot_id=uuid.uuid4(),
                org_id=config.expected_org_id,
                canonical_job_id=job_uuid,
                remote_record_id=sf_id,
                mapping_version=config.mapping_version,
                snapshot_hash=snapshot_hash,
                candidate_fields=extracted,
                source_modification_token=str(rec.get("SystemModstamp", "")),
                observed_at=now_dt,
                created_at=now_dt,
            )

            self.engine.candidate_snapshots.save_snapshot(snapshot)
            snapshots_saved += 1

        # Keyset pagination completion check:
        # If records_read < batch_size, all matching rows in scope have been returned.
        # If records_read == batch_size, more records may exist even if query_res.value.done was True for that query.
        is_finished = (records_read < batch_size) and not bool(query_res.value.next_records_url)

        self.engine.candidate_snapshots.save_checkpoint(
            checkpoint_id=checkpoint_id,
            org_id=config.expected_org_id,
            last_processed_key=highest_id,
            is_complete=is_finished,
            records_processed=snapshots_saved,
        )

        return CandidateBackupResult(
            records_read=records_read,
            snapshots_saved=snapshots_saved,
            is_complete=is_finished,
            errors=errors,
        )
