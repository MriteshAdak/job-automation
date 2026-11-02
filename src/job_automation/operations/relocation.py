"""Database path relocation for isolated restore environments (OPS-01-S07).

Enforces:
- Exact mapping of declared local absolute filesystem paths from old data root to target root.
- Preservation of relative references, content hashes, semantic IDs, and URLs.
- Transactional execution with atomic rollback on error.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from job_automation.storage.connection import transaction

logger = logging.getLogger(__name__)


def _replace_path(
    val: str | None,
    src_posix: str,
    src_win: str,
    tgt_posix: str,
    tgt_win: str,
) -> str | None:
    if not val:
        return val
    if src_win in val:
        val = val.replace(src_win, tgt_win)
    if src_posix in val:
        val = val.replace(src_posix, tgt_posix)
    return val


def _replace_json_path(
    val: str | None,
    src_posix: str,
    src_win: str,
    tgt_posix: str,
    tgt_win: str,
) -> str | None:
    if not val:
        return val
    src_json_win = src_win.replace("\\", "\\\\")
    tgt_json_win = tgt_win.replace("\\", "\\\\")
    if src_json_win in val:
        val = val.replace(src_json_win, tgt_json_win)
    if src_win in val:
        val = val.replace(src_win, tgt_win)
    if src_posix in val:
        val = val.replace(src_posix, tgt_posix)
    return val


def relocate_paths_in_database(
    conn: sqlite3.Connection,
    source_root: Path | str,
    target_root: Path | str,
) -> int:
    """Update stored absolute file paths in database tables to reflect the new target data root.

    Returns:
        total_relocated_rows: int
    """
    src_posix = Path(source_root).resolve().as_posix()
    src_win = str(Path(source_root).resolve())

    tgt_posix = Path(target_root).resolve().as_posix()
    tgt_win = str(Path(target_root).resolve())

    relocated_count = 0

    with transaction(conn):
        # 1. raw_postings.raw_payload_ref
        cursor = conn.execute(
            "SELECT provider, board_id, source_posting_id, raw_payload_ref FROM raw_postings"
        )
        for row in cursor.fetchall():
            ref = row["raw_payload_ref"]
            new_ref = _replace_path(ref, src_posix, src_win, tgt_posix, tgt_win)
            if new_ref and new_ref != ref:
                conn.execute(
                    """
                    UPDATE raw_postings
                    SET raw_payload_ref = ?
                    WHERE provider = ? AND board_id = ? AND source_posting_id = ?
                    """,
                    (new_ref, row["provider"], row["board_id"], row["source_posting_id"]),
                )
                relocated_count += 1

        # 2. normalized_postings.raw_reference & posting_json
        cur_norm = conn.execute(
            "SELECT provider, board_id, source_posting_id, raw_reference, posting_json FROM normalized_postings"
        )
        for row in cur_norm.fetchall():
            ref = row["raw_reference"]
            pjson = row["posting_json"]
            new_ref = _replace_path(ref, src_posix, src_win, tgt_posix, tgt_win)
            new_json = _replace_json_path(pjson, src_posix, src_win, tgt_posix, tgt_win)
            if (new_ref and new_ref != ref) or (new_json and new_json != pjson):
                conn.execute(
                    """
                    UPDATE normalized_postings
                    SET raw_reference = ?, posting_json = ?
                    WHERE provider = ? AND board_id = ? AND source_posting_id = ?
                    """,
                    (
                        new_ref or ref,
                        new_json or pjson,
                        row["provider"],
                        row["board_id"],
                        row["source_posting_id"],
                    ),
                )
                relocated_count += 1

        # 3. posting_bindings.raw_reference & c06_json
        cur_bind = conn.execute(
            "SELECT binding_id, raw_reference, c06_json FROM posting_bindings"
        )
        for row in cur_bind.fetchall():
            ref = row["raw_reference"]
            c06 = row["c06_json"]
            new_ref = _replace_path(ref, src_posix, src_win, tgt_posix, tgt_win)
            new_c06 = _replace_json_path(c06, src_posix, src_win, tgt_posix, tgt_win)
            if (new_ref and new_ref != ref) or (new_c06 and new_c06 != c06):
                conn.execute(
                    """
                    UPDATE posting_bindings
                    SET raw_reference = ?, c06_json = ?
                    WHERE binding_id = ?
                    """,
                    (new_ref or ref, new_c06 or c06, row["binding_id"]),
                )
                relocated_count += 1

        # 4. quarantine_records.raw_reference
        cur_quar = conn.execute(
            "SELECT quarantine_id, raw_reference FROM quarantine_records"
        )
        for row in cur_quar.fetchall():
            ref = row["raw_reference"]
            new_ref = _replace_path(ref, src_posix, src_win, tgt_posix, tgt_win)
            if new_ref and new_ref != ref:
                conn.execute(
                    "UPDATE quarantine_records SET raw_reference = ? WHERE quarantine_id = ?",
                    (new_ref, row["quarantine_id"]),
                )
                relocated_count += 1

        # 5. generation_requests.result_artifact_ref & request_json
        cur_req = conn.execute(
            "SELECT request_id, result_artifact_ref, request_json FROM generation_requests"
        )
        for row in cur_req.fetchall():
            ref = row["result_artifact_ref"]
            rjson = row["request_json"]
            new_ref = _replace_path(ref, src_posix, src_win, tgt_posix, tgt_win)
            new_json = _replace_json_path(rjson, src_posix, src_win, tgt_posix, tgt_win)
            if (new_ref and new_ref != ref) or (new_json and new_json != rjson):
                conn.execute(
                    """
                    UPDATE generation_requests
                    SET result_artifact_ref = ?, request_json = ?
                    WHERE request_id = ?
                    """,
                    (new_ref or ref, new_json or rjson, row["request_id"]),
                )
                relocated_count += 1

        # 6. artifacts.local_path & artifact_json
        cur_art = conn.execute(
            "SELECT artifact_id, local_path, artifact_json FROM artifacts"
        )
        for row in cur_art.fetchall():
            ref = row["local_path"]
            ajson = row["artifact_json"]
            new_ref = _replace_path(ref, src_posix, src_win, tgt_posix, tgt_win)
            new_json = _replace_json_path(ajson, src_posix, src_win, tgt_posix, tgt_win)
            if (new_ref and new_ref != ref) or (new_json and new_json != ajson):
                conn.execute(
                    """
                    UPDATE artifacts
                    SET local_path = ?, artifact_json = ?
                    WHERE artifact_id = ?
                    """,
                    (new_ref or ref, new_json or ajson, row["artifact_id"]),
                )
                relocated_count += 1

        # 7. context_index_generations.generation_dir & manifest_json
        cur_gen = conn.execute(
            "SELECT generation_id, generation_dir, manifest_json FROM context_index_generations"
        )
        for row in cur_gen.fetchall():
            ref = row["generation_dir"]
            mjson = row["manifest_json"]
            new_ref = _replace_path(ref, src_posix, src_win, tgt_posix, tgt_win)
            new_json = _replace_json_path(mjson, src_posix, src_win, tgt_posix, tgt_win)
            if (new_ref and new_ref != ref) or (new_json and new_json != mjson):
                conn.execute(
                    """
                    UPDATE context_index_generations
                    SET generation_dir = ?, manifest_json = ?
                    WHERE generation_id = ?
                    """,
                    (new_ref or ref, new_json or mjson, row["generation_id"]),
                )
                relocated_count += 1

        # 8. rendered_artifact_receipts.local_path (GEN-05)
        has_receipts = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rendered_artifact_receipts'"
        ).fetchone()
        if has_receipts:
            cur_rend = conn.execute(
                "SELECT receipt_id, local_path FROM rendered_artifact_receipts"
            )
            for row in cur_rend.fetchall():
                ref = row["local_path"]
                new_ref = _replace_path(ref, src_posix, src_win, tgt_posix, tgt_win)
                if new_ref and new_ref != ref:
                    conn.execute(
                        """
                        UPDATE rendered_artifact_receipts
                        SET local_path = ?
                        WHERE receipt_id = ?
                        """,
                        (new_ref, row["receipt_id"]),
                    )
                    relocated_count += 1

    return relocated_count
