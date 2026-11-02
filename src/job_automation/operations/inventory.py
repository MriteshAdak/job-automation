"""Retention inventory scanner and reference graph builder (OPS-01-S01).

Traverses database tables (through migration 009) and managed filesystem roots.
Constructs a complete reference graph, identifies unreferenced bulky data,
enforces protection closure, and accounts for files without duplication.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING
import uuid

from job_automation.operations.records import (
    InventoryItem,
    ItemClass,
    ProtectionReason,
    RetentionInventory,
)
if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine
from job_automation.storage.filestore import compute_sha256

logger = logging.getLogger(__name__)


def compute_store_fingerprint(engine: StorageEngine) -> tuple[str, dict[str, int]]:
    """Compute deterministic fingerprint of database schema and table row counts."""
    conn = engine.conn
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'ops_%' ORDER BY name ASC"
    )
    table_names = [row["name"] for row in cursor.fetchall()]

    counts: dict[str, int] = {}
    fingerprint_parts: list[str] = []

    for tbl in table_names:
        c_cur = conn.execute(f"SELECT COUNT(*) as cnt FROM [{tbl}]")
        count = int(c_cur.fetchone()["cnt"])
        counts[tbl] = count
        fingerprint_parts.append(f"{tbl}:{count}")

    # Add schema migration version
    ver = engine.get_schema_version()
    fingerprint_parts.append(f"schema_v:{ver}")

    fp_str = ";".join(fingerprint_parts)
    return hashlib.sha256(fp_str.encode("utf-8")).hexdigest(), counts


def normalize_rel_path(p: Path | str, base_dir: Path) -> str:
    """Normalize path relative to base directory with forward slashes."""
    try:
        path_obj = Path(p).resolve()
        base_obj = base_dir.resolve()
        rel = path_obj.relative_to(base_obj)
        return rel.as_posix()
    except (ValueError, RuntimeError):
        # Fallback if path is already relative
        return Path(p).as_posix()


class RetentionInventoryManager:
    """Discovers managed storage items and builds the reference/protection graph."""

    def __init__(self, data_root: Path | str) -> None:
        self.data_root = Path(data_root).resolve()

    def build_inventory(self, engine: StorageEngine) -> RetentionInventory:
        """Scan SQLite store and managed filesystem directories."""
        store_fp, table_counts = compute_store_fingerprint(engine)
        conn = engine.conn

        # Map: root_relative_path -> dict of metadata
        # keys: "item_class", "referencing_records", "protection_reasons", "is_referenced"
        file_ref_map: dict[str, dict[str, Any]] = {}

        def _track_file_ref(
            path_val: str | Path | None,
            item_class: ItemClass,
            record_ref: str,
            protection_reason: ProtectionReason | None = None,
        ) -> None:
            if not path_val:
                return
            rel = normalize_rel_path(path_val, self.data_root)
            if rel not in file_ref_map:
                file_ref_map[rel] = {
                    "item_class": item_class,
                    "referencing_records": set(),
                    "protection_reasons": set(),
                    "is_referenced": True,
                }
            file_ref_map[rel]["referencing_records"].add(record_ref)
            if protection_reason:
                file_ref_map[rel]["protection_reasons"].add(protection_reason)

        # 1. Database file itself
        db_rel = normalize_rel_path(engine.db_path, self.data_root)
        file_ref_map[db_rel] = {
            "item_class": ItemClass.DATABASE,
            "referencing_records": {"system:database"},
            "protection_reasons": {ProtectionReason.REFERENCED_BY_RECORD},
            "is_referenced": True,
        }

        # Content, audits and their exact input bodies live inside SQLite, not
        # in artifact files. Preserve failed/interrupted attempts as well.
        for table, key in (("generation_frozen_seals", "seal_id"),
                           ("generation_context_receipts", "receipt_id"),
                           ("draft_content_attempts", "attempt_id"),
                           ("draft_model_audits", "call_id"),
                           ("document_validation_attempts", "attempt_id"),
                           ("render_intents", "intent_id"),
                           ("render_attempts", "attempt_id"),
                           ("rendered_artifact_receipts", "receipt_id"),
                           ("artifact_sets", "set_id")):
            if table in table_counts:
                for row in conn.execute(f"SELECT [{key}] FROM [{table}]"):
                    file_ref_map[db_rel]["referencing_records"].add(f"{table}:{row[key]}")

        # 2. Raw Postings
        cursor = conn.execute(
            "SELECT provider, board_id, source_posting_id, raw_payload_ref FROM raw_postings"
        )
        for row in cursor.fetchall():
            ref_str = f"raw_postings:{row['provider']}/{row['board_id']}/{row['source_posting_id']}"
            _track_file_ref(
                row["raw_payload_ref"],
                ItemClass.RAW_PAYLOAD,
                ref_str,
                ProtectionReason.REFERENCED_BY_RECORD,
            )

        # Check references in posting_bindings, posting_revisions, quarantine_records
        cursor = conn.execute(
            "SELECT provider, board_id, source_posting_id FROM posting_bindings"
        )
        for row in cursor.fetchall():
            ref_str = f"posting_bindings:{row['provider']}/{row['board_id']}/{row['source_posting_id']}"
            # Mark raw posting referenced
            raw_cur = conn.execute(
                "SELECT raw_payload_ref FROM raw_postings WHERE provider=? AND board_id=? AND source_posting_id=?",
                (row["provider"], row["board_id"], row["source_posting_id"]),
            )
            r_row = raw_cur.fetchone()
            if r_row:
                _track_file_ref(
                    r_row["raw_payload_ref"],
                    ItemClass.RAW_PAYLOAD,
                    ref_str,
                    ProtectionReason.REFERENCED_BY_RECORD,
                )

        # 3. Artifacts
        cursor = conn.execute(
            "SELECT artifact_id, local_path, delivery_status FROM artifacts"
        )
        for row in cursor.fetchall():
            ref_str = f"artifacts:{row['artifact_id']}"
            reasons = {ProtectionReason.REFERENCED_BY_RECORD}
            if row["delivery_status"] in ("pending", "upload_pending"):
                reasons.add(ProtectionReason.UNFINISHED_WORK)
            rel = normalize_rel_path(row["local_path"], self.data_root)
            if rel not in file_ref_map:
                file_ref_map[rel] = {
                    "item_class": ItemClass.ARTIFACT,
                    "referencing_records": set(),
                    "protection_reasons": set(),
                    "is_referenced": True,
                }
            file_ref_map[rel]["referencing_records"].add(ref_str)
            file_ref_map[rel]["protection_reasons"].update(reasons)

        # 3b. Rendered Artifact Receipts (GEN-05)
        if "rendered_artifact_receipts" in table_counts:
            cursor = conn.execute(
                "SELECT receipt_id, local_path FROM rendered_artifact_receipts"
            )
            for row in cursor.fetchall():
                ref_str = f"rendered_artifact_receipts:{row['receipt_id']}"
                _track_file_ref(
                    row["local_path"],
                    ItemClass.ARTIFACT,
                    ref_str,
                    ProtectionReason.REFERENCED_BY_RECORD,
                )

        # 4. Context Indexes
        cursor = conn.execute(
            """
            SELECT generation_id, purpose, status, generation_dir, manifest_json
            FROM context_index_generations
            """
        )
        for row in cursor.fetchall():
            gen_id = uuid.UUID(row["generation_id"])
            is_pinned = engine.context_indexes.is_generation_pinned(gen_id)
            status = row["status"]

            # If generation is active, building, or pinned, all files in generation_dir are protected
            gen_dir = Path(row["generation_dir"])

            reasons: set[ProtectionReason] = set()
            if status in ("active", "building"):
                reasons.add(ProtectionReason.ACTIVE_INDEX)
            elif is_pinned:
                reasons.add(ProtectionReason.PINNED_INDEX)
            elif status == "retired":
                # Check retention count: if within default keep count (2), protect
                reasons.add(ProtectionReason.WITHIN_RETENTION_PERIOD)

            if gen_dir.exists():
                for root, _, files in os.walk(gen_dir):
                    for fn in files:
                        fp = Path(root) / fn
                        _track_file_ref(
                            fp,
                            ItemClass.CONTEXT_INDEX,
                            f"context_index_generations:{gen_id}",
                            next(iter(reasons)) if reasons else None,
                        )

        # 5. Profile Snapshots and evidence files
        cursor = conn.execute("SELECT profile_version, snapshot_json FROM profiles")
        for row in cursor.fetchall():
            ref_str = f"profiles:{row['profile_version']}"
            try:
                data = json.loads(row["snapshot_json"])
                # Look for evidence references
                facts = data.get("facts", [])
                for f in facts:
                    ev_list = f.get("evidence", [])
                    for ev in ev_list:
                        ev_path = ev.get("evidence_path")
                        if ev_path:
                            _track_file_ref(
                                ev_path,
                                ItemClass.PROFILE_EVIDENCE,
                                f"{ref_str}:fact:{f.get('fact_id')}",
                                ProtectionReason.PROFILE_FACT,
                            )
            except Exception:
                pass

        # 6. Unfinished Work Checks
        # Pending generation requests
        cursor = conn.execute(
            "SELECT request_id, state FROM generation_requests WHERE state IN ('pending', 'running', 'upload_pending')"
        )
        for row in cursor.fetchall():
            # If an unfinished request exists, protect related artifacts
            a_cur = conn.execute(
                "SELECT local_path FROM artifacts WHERE request_id = ?",
                (row["request_id"],),
            )
            for a_row in a_cur.fetchall():
                _track_file_ref(
                    a_row["local_path"],
                    ItemClass.ARTIFACT,
                    f"generation_requests:{row['request_id']}",
                    ProtectionReason.UNFINISHED_WORK,
                )

        # Sync operations pending work
        cursor = conn.execute(
            "SELECT operation_id, state, canonical_job_id FROM sync_operations WHERE state IN ('pending', 'running', 'retry_wait', 'uncertain')"
        )
        for row in cursor.fetchall():
            # Pending sync outbox work protects related job's raw postings
            c_job_id = row["canonical_job_id"]
            if c_job_id:
                bind_cur = conn.execute(
                    "SELECT provider, board_id, source_posting_id FROM posting_bindings WHERE canonical_job_id = ?",
                    (c_job_id,),
                )
                for b_row in bind_cur.fetchall():
                    raw_cur = conn.execute(
                        "SELECT raw_payload_ref FROM raw_postings WHERE provider=? AND board_id=? AND source_posting_id=?",
                        (b_row["provider"], b_row["board_id"], b_row["source_posting_id"]),
                    )
                    r_row = raw_cur.fetchone()
                    if r_row:
                        _track_file_ref(
                            r_row["raw_payload_ref"],
                            ItemClass.RAW_PAYLOAD,
                            f"sync_operations:{row['operation_id']}",
                            ProtectionReason.UNFINISHED_WORK,
                        )

        # 7. Scan Physical Files on Disk
        items: list[InventoryItem] = []
        unknown_files: list[str] = []
        seen_paths: set[str] = set()

        # Directories to scan beneath data_root
        scan_subdirs = ["raw", "artifacts", "profiles", "indexes", "logs", "database"]
        now_dt = datetime.now(timezone.utc)

        for subdir_name in scan_subdirs:
            subdir_path = self.data_root / subdir_name
            if not subdir_path.exists():
                continue

            for root, _, files in os.walk(subdir_path):
                for fname in files:
                    full_p = Path(root) / fname
                    rel = normalize_rel_path(full_p, self.data_root)
                    if rel in seen_paths:
                        continue
                    seen_paths.add(rel)

                    # Compute file stats and hash
                    try:
                        file_bytes = full_p.read_bytes()
                        content_hash = compute_sha256(file_bytes)
                        size_bytes = len(file_bytes)
                        mtime_dt = datetime.fromtimestamp(full_p.stat().st_mtime, tz=timezone.utc)
                    except (OSError, PermissionError) as exc:
                        logger.warning("Could not read file %s: %s", full_p, exc)
                        continue

                    # Look up in reference map
                    if rel in file_ref_map:
                        meta = file_ref_map[rel]
                        item_class = meta["item_class"]
                        ref_records = sorted(meta["referencing_records"])
                        reasons = sorted(meta["protection_reasons"])
                        is_referenced = True
                        is_protected = True
                    else:
                        # File is physically on disk, but NOT in DB reference map
                        is_referenced = False
                        ref_records = []
                        reasons = []

                        if subdir_name == "raw":
                            item_class = ItemClass.RAW_PAYLOAD
                        elif subdir_name == "artifacts":
                            item_class = ItemClass.ARTIFACT
                            # In OPS v1, unreferenced artifacts are protected
                            reasons.append(ProtectionReason.REFERENCED_BY_RECORD)
                        elif subdir_name == "profiles":
                            item_class = ItemClass.PROFILE_EVIDENCE
                            reasons.append(ProtectionReason.PROFILE_FACT)
                        elif subdir_name == "indexes":
                            item_class = ItemClass.CONTEXT_INDEX
                        elif subdir_name == "logs":
                            item_class = ItemClass.LOG
                        elif subdir_name == "database":
                            item_class = ItemClass.DATABASE
                            reasons.append(ProtectionReason.REFERENCED_BY_RECORD)
                        else:
                            item_class = ItemClass.UNKNOWN
                            reasons.append(ProtectionReason.UNKNOWN_SCHEMA_OR_FORMAT)
                            unknown_files.append(rel)

                        is_protected = len(reasons) > 0

                    items.append(
                        InventoryItem(
                            item_id=rel,
                            root_relative_path=rel,
                            item_class=item_class,
                            size_bytes=size_bytes,
                            content_hash=content_hash,
                            observed_at=mtime_dt,
                            is_referenced=is_referenced,
                            referencing_records=ref_records,
                            is_protected=is_protected,
                            protection_reasons=reasons,
                        )
                    )

        # Protection summary
        protection_summary: dict[str, int] = {}
        for it in items:
            for r in it.protection_reasons:
                r_val = r.value if hasattr(r, "value") else str(r)
                protection_summary[r_val] = protection_summary.get(r_val, 0) + 1

        total_bytes = sum(it.size_bytes for it in items)

        return RetentionInventory(
            inventory_id=uuid.uuid4(),
            data_root=str(self.data_root),
            scanned_at=now_dt,
            store_fingerprint=store_fp,
            total_files_count=len(items),
            total_files_bytes=total_bytes,
            items=items,
            table_counts=table_counts,
            unknown_files=unknown_files,
            protection_summary=protection_summary,
        )
