"""Manual smoke verification script for OPS-01 disaster recovery restore.

Validates end-to-end disaster recovery workflow in native Windows environment:
1. Provisions isolated synthetic source, backup, and target directories.
   The target directory explicitly exercises Windows spaces and umlauts
   (e.g., 'Wiederherstellung Prüfung / Target Restore 2026').
2. Seeds multi-version synthetic data:
   - Canonical jobs and posting revisions
   - Raw payload snapshot files on disk and references
   - Generation requests and physical PDF artifacts
   - Context index generations on disk
   - Sync outbox operations
3. Performs storage capacity evaluation.
4. Generates a retention cleanup preview verifying protection closure.
5. Creates a point-in-time backup set.
6. Verifies backup integrity, checksums, and completion marker.
7. Pre-flights restore into target directory via RestorePlan.
8. Applies restore into isolation, executing SQLite backup relocation.
9. Validates cross-record link preservation, path rewriting, and file fidelity.
10. Cleans up all synthetic artifacts.

Usage:
  python tests/manual/operations_restore_smoke.py
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from job_automation.contracts.artifacts import Artifact, DocumentApproval
from job_automation.contracts.enums import (
    AssessmentDisposition,
    DocumentType,
    GenerationProcessing,
    PostingAvailability,
)
from job_automation.contracts.generation import FrozenInputVersions, GenerationRequest
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.sync import SyncOperation, SyncPayload
from job_automation.operations.backup import create_backup
from job_automation.operations.capacity import check_capacity
from job_automation.operations.inventory import RetentionInventoryManager
from job_automation.operations.preview import generate_cleanup_preview
from job_automation.operations.records import OperationsSettings
from job_automation.operations.restore import apply_restore, plan_restore
from job_automation.operations.verification import verify_backup
from job_automation.storage.engine import StorageEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ops_smoke")


def run_smoke_drill() -> int:
    """Execute end-to-end restore smoke drill."""
    temp_dir = tempfile.mkdtemp(prefix="ops_smoke_")
    base_path = Path(temp_dir).resolve()
    logger.info("Created temporary test sandbox: %s", base_path)

    try:
        src_root = base_path / "source_data_root"
        src_root.mkdir()
        backups_dir = base_path / "backups_archive"
        backups_dir.mkdir()

        # Target directory with spaces and German umlauts
        target_root = base_path / "Wiederherstellung Prüfung" / "Target Restore 2026"

        settings = OperationsSettings()

        # 1. Initialize Storage Engine and apply migrations
        logger.info("[Step 1] Initializing source storage engine at: %s", src_root)
        engine = StorageEngine(
            db_path=src_root / "database" / "job_automation.db",
            raw_dir=src_root / "raw",
            artifacts_dir=src_root / "artifacts",
        )
        applied_mig = engine.migrate()
        logger.info("Applied %d storage migrations.", len(applied_mig))

        # 2. Seed multi-version synthetic data
        logger.info("[Step 2] Seeding multi-version synthetic data...")
        now_dt = datetime.now(timezone.utc)
        job_id = uuid.uuid4()
        rev_id = uuid.uuid4()
        req_id = uuid.uuid4()
        art_id = uuid.uuid4()
        op_id = uuid.uuid4()
        gen_id = uuid.uuid4()

        # Raw posting payload file
        raw_payload = b"<html><body>Synthetic Job Posting Content</body></html>"
        raw_file, raw_hash = engine.filestore.save_raw_payload(
            provider="arbeitsagentur",
            board_id="it_jobs",
            source_posting_id="posting-999",
            payload=raw_payload,
            suffix=".html",
        )
        with engine.conn:
            engine.conn.execute(
                """
                INSERT INTO raw_postings (provider, board_id, source_posting_id, raw_payload_ref, raw_content_hash, fetch_time, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                ("arbeitsagentur", "it_jobs", "posting-999", raw_file, raw_hash, now_dt.isoformat(), now_dt.isoformat()),
            )

        # Canonical Job
        engine.canonical_jobs.save_canonical_job(
            CanonicalJob(
                canonical_job_id=job_id,
                company_name="Musterfirma Technologies GmbH",
                current_revision_id=rev_id,
                first_seen_at=now_dt,
                last_seen_at=now_dt,
            )
        )

        # Posting revision
        engine.canonical_jobs.save_revision(
            PostingRevision(
                revision_id=rev_id,
                canonical_job_id=job_id,
                source_key=SourceKey(
                    provider="arbeitsagentur",
                    board_id="it_jobs",
                    source_posting_id="posting-999",
                ),
                content_hash=raw_hash,
                title="Senior Solutions Architect",
                availability=PostingAvailability.ACTIVE,
                first_seen_at=now_dt,
                last_seen_at=now_dt,
            )
        )

        # Generation Request
        engine.generation_requests.create_request(
            GenerationRequest(
                request_id=req_id,
                canonical_job_id=job_id,
                document_type=DocumentType.CV,
                template_id="cv_executive_de",
                created_at=now_dt,
                state=GenerationProcessing.READY_FOR_REVIEW,
                frozen_input_versions=FrozenInputVersions(
                    posting_revision="rev-1",
                    profile_version="1",
                    policy_version="1",
                    template_version="1",
                ),
            )
        )

        # Artifact PDF file
        art_path, art_hash, art_size = engine.filestore.save_artifact_file(
            request_id=req_id,
            filename="Lebenslauf_Mustermann.pdf",
            content=b"%PDF-1.4 synthetic curriculum vitae for testing",
        )
        engine.artifacts.save_artifact(
            Artifact(
                artifact_id=art_id,
                request_id=req_id,
                format="pdf",
                local_path=art_path,
                content_hash=art_hash,
                size_bytes=art_size,
                delivery_status="local_only",
                approval_status=DocumentApproval.DRAFT,
                created_at=now_dt,
            )
        )

        # Context Index Directory
        index_dir = src_root / "indexes" / "profile_v1_search"
        index_dir.mkdir(parents=True)
        (index_dir / "index_manifest.json").write_text('{"dimension": 1536, "rows": 42}', encoding="utf-8")
        (index_dir / "embeddings.bin").write_bytes(b"\x00" * 256)
        with engine.conn:
            engine.conn.execute(
                """
                INSERT INTO context_index_generations (
                    generation_id, candidate_id, profile_version, purpose,
                    snapshot_fingerprint, chunk_manifest_hash, embedding_space_fingerprint,
                    settings_fingerprint, logical_build_fingerprint, artifact_fingerprint,
                    status, row_count, dimension, generation_dir, manifest_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(gen_id), "cand-1", "1", "search", "fp1", "cmh1", "esf1",
                    "sf1", "lbf1", "af1", "active", 42, 1536, str(index_dir),
                    '{"dim": 1536}', now_dt.isoformat(),
                ),
            )

        # Sync Operation in Outbox
        sync_payload = SyncPayload(
            canonical_job_id=job_id,
            job_title="Senior Solutions Architect",
            company_name="Musterfirma Technologies GmbH",
            availability=PostingAvailability.ACTIVE,
            assessment_disposition=AssessmentDisposition.ELIGIBLE,
            assessment_reasons="High alignment with experience profile",
            last_evaluated_at=now_dt,
        )
        engine.sync_outbox.enqueue_operation(
            SyncOperation(
                operation_id=op_id,
                canonical_job_id=job_id,
                payload_version="1.0",
                payload_fingerprint="fp_synthetic",
                locally_owned_payload=sync_payload,
                attempt_count=0,
            )
        )
        logger.info("Synthetic database records and filesystem files successfully committed.")

        # 3. Storage Capacity Check
        logger.info("[Step 3] Checking storage capacity...")
        cap_report = check_capacity(
            settings=settings,
            source_root=src_root,
            destination_path=backups_dir,
        )
        logger.info("Capacity status: %s (Source free: %.2f GiB)", cap_report.overall_status.value, cap_report.source_volume.free_bytes / (1024**3))

        # 4. Cleanup Preview
        logger.info("[Step 4] Generating retention cleanup preview...")
        inv_mgr = RetentionInventoryManager(data_root=src_root)
        inventory = inv_mgr.build_inventory(engine)
        cleanup_plan = generate_cleanup_preview(
            inventory=inventory,
            settings=settings,
            engine=engine,
        )
        logger.info("Cleanup preview: %d candidates eligible, %d items protected.", len(cleanup_plan.candidates), cleanup_plan.protected_items_count)
        assert cleanup_plan.protected_items_count > 0, "Active data must be protected"

        # 5. Create Backup
        logger.info("[Step 5] Creating point-in-time backup...")
        manifest, backup_path = create_backup(
            settings=settings,
            data_root=src_root,
            engine=engine,
            destination_override=backups_dir,
            local_only=True,
        )
        logger.info("Backup created at: %s (ID: %s, Files: %d, Bytes: %d)", backup_path, manifest.backup_id, manifest.total_files_count, manifest.total_bytes)

        # 6. Verify Backup
        logger.info("[Step 6] Verifying backup set integrity...")
        is_valid, issues = verify_backup(backup_path)
        assert is_valid, f"Backup validation failed: {issues}"
        logger.info("Backup verification passed with 0 issues.")

        # 7. Plan Restore into Target (with spaces and umlauts)
        logger.info("[Step 7] Planning restore into target with spaces and umlauts: %s", target_root)
        restore_plan = plan_restore(
            backup_path=backup_path,
            target_data_root=target_root,
            settings=settings,
        )
        assert restore_plan.is_valid, f"Restore plan invalid: {restore_plan.conflicts}"
        logger.info("Restore plan validated: %d files to copy, %d path mappings.", restore_plan.files_to_restore, restore_plan.path_mappings_count)

        # 8. Apply Restore
        logger.info("[Step 8] Applying restore into isolated target directory...")
        restore_result = apply_restore(plan=restore_plan, settings=settings)
        assert restore_result.status.value == "succeeded", f"Restore apply failed: {restore_result.issues}"
        logger.info("Restore succeeded: %d files restored, %d paths relocated in DB.", restore_result.restored_files_count, restore_result.relocated_paths_count)
        assert restore_result.integrity_check_passed, "SQLite PRAGMA integrity_check must pass"
        assert restore_result.foreign_key_check_passed, "SQLite foreign_key_check must pass"

        # 9. Verify Restored Data Integrity in Isolation
        logger.info("[Step 9] Verifying restored data fidelity in target root...")
        restored_engine = StorageEngine(
            db_path=target_root / "database" / "job_automation.db",
            raw_dir=target_root / "raw",
            artifacts_dir=target_root / "artifacts",
        )
        try:
            # Canonical job
            c_job = restored_engine.canonical_jobs.get_canonical_job(job_id)
            assert c_job is not None
            assert c_job.company_name == "Musterfirma Technologies GmbH"

            # Generation request
            req = restored_engine.generation_requests.get_request(req_id)
            assert req is not None
            assert req.canonical_job_id == job_id

            # Artifact
            art = restored_engine.artifacts.get_artifact(art_id)
            assert art is not None
            assert art.request_id == req_id
            assert art.content_hash == art_hash
            assert str(target_root) in art.local_path
            assert Path(art.local_path).is_file()
            assert Path(art.local_path).read_bytes() == b"%PDF-1.4 synthetic curriculum vitae for testing"

            # Raw posting payload
            cursor = restored_engine.conn.execute(
                "SELECT raw_payload_ref FROM raw_postings WHERE provider = 'arbeitsagentur' AND source_posting_id = 'posting-999'"
            )
            raw_row = cursor.fetchone()
            assert raw_row is not None
            restored_raw_path = Path(raw_row["raw_payload_ref"])
            assert str(target_root) in str(restored_raw_path)
            assert restored_raw_path.is_file()
            assert restored_raw_path.read_bytes() == raw_payload

            # Context Index files
            cursor_idx = restored_engine.conn.execute("SELECT generation_dir FROM context_index_generations WHERE generation_id = ?", (str(gen_id),))
            idx_row = cursor_idx.fetchone()
            assert idx_row is not None
            restored_idx_dir = Path(idx_row["generation_dir"])
            assert str(target_root) in str(restored_idx_dir)
            assert (restored_idx_dir / "index_manifest.json").is_file()
            assert (restored_idx_dir / "embeddings.bin").is_file()

            # Sync outbox operation
            cur_sync = restored_engine.conn.execute("SELECT operation_id, state FROM sync_operations WHERE operation_id = ?", (str(op_id),))
            s_row = cur_sync.fetchone()
            assert s_row is not None
            assert s_row["state"] == "pending"

            logger.info("All restored data entities, files, hashes, and relational links verified!")
        finally:
            restored_engine.close()
            engine.close()

        logger.info("[SUCCESS] Full operations disaster recovery smoke drill completed successfully.")
        return 0

    finally:
        logger.info("Cleaning up temporary test sandbox: %s", base_path)
        shutil.rmtree(base_path, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(run_smoke_drill())
