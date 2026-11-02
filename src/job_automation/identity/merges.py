"""Reversible canonical job merge and reversal operations preserving linked history."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from job_automation.contracts.enums import PostingAvailability
from job_automation.contracts.identity import CanonicalJob, PostingRevision
from job_automation.contracts.primitives import SourceKey
from job_automation.identity.errors import InvalidOperationError, MergeError, ReversalError
from job_automation.identity.models import MergeOperation, ReversalOperation
from job_automation.identity.revisions import select_current_revision
from job_automation.storage.connection import transaction

if TYPE_CHECKING:
    from job_automation.storage.repositories.canonical_jobs import CanonicalJobRepository
    from job_automation.storage.repositories.identity import IdentityRepository


def execute_merge(
    surviving_id: uuid.UUID,
    merged_id: uuid.UUID,
    actor: str,
    reason: str,
    canonical_repo: CanonicalJobRepository,
    identity_repo: IdentityRepository,
) -> MergeOperation:
    """Merge predecessor canonical job into surviving canonical job atomically."""
    if surviving_id == merged_id:
        raise InvalidOperationError(f"Cannot merge canonical job {surviving_id} with itself")

    with transaction(canonical_repo.conn):
        surviving_job = canonical_repo.get_canonical_job(surviving_id)
        if not surviving_job:
            raise MergeError(f"Surviving canonical job not found: {surviving_id}")

        merged_job = canonical_repo.get_canonical_job(merged_id)
        if not merged_job:
            raise MergeError(f"Merged canonical job not found: {merged_id}")

        operation_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # Capture pre-merge state snapshots
        details = {
            "surviving_pre_merge": surviving_job.model_dump(mode="json"),
            "merged_pre_merge": merged_job.model_dump(mode="json"),
            "merged_source_keys": [sk.model_dump() for sk in merged_job.linked_source_keys],
            "merged_revision_ids": [str(r.revision_id) for r in merged_job.revisions],
        }

        # 1. Reassign source identities
        for sk in merged_job.linked_source_keys:
            identity_repo.reassign_source_key(sk, surviving_id, updated_at=now)

        # 2. Reassign posting revisions in storage
        for rev in merged_job.revisions:
            canonical_repo.conn.execute(
                """
                UPDATE posting_revisions
                SET canonical_job_id = ?
                WHERE revision_id = ?
                """,
                (str(surviving_id), str(rev.revision_id)),
            )

        # 3. Combine source keys (preserving order, removing duplicates)
        combined_source_keys: list[SourceKey] = list(surviving_job.linked_source_keys)
        for sk in merged_job.linked_source_keys:
            if sk not in combined_source_keys:
                combined_source_keys.append(sk)

        # 4. Combine revisions
        updated_merged_revs = [
            r.model_copy(update={"canonical_job_id": surviving_id})
            for r in merged_job.revisions
        ]
        combined_revisions: list[PostingRevision] = list(surviving_job.revisions) + updated_merged_revs

        # 5. Determine active revision and time boundaries
        current_rev_id = select_current_revision(combined_revisions)
        first_seen = min(surviving_job.first_seen_at, merged_job.first_seen_at)
        last_seen = max(surviving_job.last_seen_at, merged_job.last_seen_at)

        # 6. Update surviving job
        merge_audit_msg = (
            f"MERGE: op={operation_id} merged {merged_id} into {surviving_id} "
            f"by {actor} at {now_iso}: {reason}"
        )
        updated_survivor = surviving_job.model_copy(
            update={
                "linked_source_keys": combined_source_keys,
                "revisions": combined_revisions,
                "current_revision_id": current_rev_id,
                "first_seen_at": first_seen,
                "last_seen_at": last_seen,
                "merge_lineage": surviving_job.merge_lineage + [merge_audit_msg],
            }
        )
        canonical_repo.save_canonical_job(updated_survivor)

        # 7. Update merged job to preserve record and retain lineage
        updated_merged = merged_job.model_copy(
            update={
                "linked_source_keys": [],
                "revisions": [],
                "duplicate_proposal_reason": f"Merged into {surviving_id} (op={operation_id})",
                "merge_lineage": merged_job.merge_lineage + [
                    f"MERGED_INTO: {surviving_id} by {actor} at {now_iso}: {reason}"
                ],
            }
        )
        canonical_repo.save_canonical_job(updated_merged)

        # 8. Record merge event
        identity_repo.save_merge_event(
            operation_id=operation_id,
            operation_type="merge",
            surviving_canonical_id=surviving_id,
            merged_canonical_id=merged_id,
            actor=actor,
            reason=reason,
            details=details,
        )

        return MergeOperation(
            operation_id=operation_id,
            operation_type="merge",
            surviving_canonical_id=surviving_id,
            merged_canonical_id=merged_id,
            actor=actor,
            reason=reason,
            details=details,
            created_at=now,
        )


def execute_reversal(
    operation_id: str,
    actor: str,
    reason: str,
    canonical_repo: CanonicalJobRepository,
    identity_repo: IdentityRepository,
) -> ReversalOperation:
    """Reverse a prior merge operation restoring original identities and linked history."""
    with transaction(canonical_repo.conn):
        event = identity_repo.get_merge_event(operation_id)
        if not event:
            raise ReversalError(f"Merge operation '{operation_id}' not found")

        if event.get("reversed_at"):
            raise ReversalError(
                f"Merge operation '{operation_id}' was already reversed at {event['reversed_at']}"
            )

        surviving_id = event["surviving_canonical_id"]
        merged_id = event["merged_canonical_id"]
        details = event["details"]
        merged_pre_merge = CanonicalJob.model_validate(details["merged_pre_merge"])
        pre_merged_source_keys = [
            SourceKey.model_validate(sk) for sk in details["merged_source_keys"]
        ]

        surviving_job = canonical_repo.get_canonical_job(surviving_id)
        if not surviving_job:
            raise ReversalError(f"Surviving canonical job not found: {surviving_id}")

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        reversal_op_id = str(uuid.uuid4())

        # 1. Partition revisions: those belonging to merged job's sources vs surviving job's sources
        restored_revisions: list[PostingRevision] = []
        survivor_revisions: list[PostingRevision] = []

        for r in surviving_job.revisions:
            if r.source_key in pre_merged_source_keys:
                restored_revisions.append(r.model_copy(update={"canonical_job_id": merged_id}))
            else:
                survivor_revisions.append(r)

        # Fallback to pre-merge revisions if none matched
        if not restored_revisions:
            restored_revisions = merged_pre_merge.revisions

        # 2. Update posting revisions in SQLite storage
        for r in restored_revisions:
            canonical_repo.conn.execute(
                """
                UPDATE posting_revisions
                SET canonical_job_id = ?
                WHERE revision_id = ?
                """,
                (str(merged_id), str(r.revision_id)),
            )

        # 3. Reassign source identities in storage
        for sk in pre_merged_source_keys:
            identity_repo.reassign_source_key(sk, merged_id, updated_at=now)

        # 4. Restore merged canonical job
        restored_cur_rev = select_current_revision(restored_revisions)
        restored_first_seen = min(r.first_seen_at for r in restored_revisions)
        restored_last_seen = max(r.last_seen_at for r in restored_revisions)
        restored_audit_msg = (
            f"REVERSAL: op={operation_id} reversed by {actor} at {now_iso}: {reason}"
        )

        restored_job = CanonicalJob(
            canonical_job_id=merged_id,
            canonical_company_id=merged_pre_merge.canonical_company_id,
            company_name=merged_pre_merge.company_name,
            linked_source_keys=pre_merged_source_keys,
            revisions=restored_revisions,
            current_revision_id=restored_cur_rev,
            first_seen_at=restored_first_seen,
            last_seen_at=restored_last_seen,
            availability=merged_pre_merge.availability,
            merge_lineage=merged_pre_merge.merge_lineage + [restored_audit_msg],
            duplicate_proposal_reason=None,
        )
        canonical_repo.save_canonical_job(restored_job)

        # 5. Restore surviving canonical job
        survivor_source_keys = [
            sk for sk in surviving_job.linked_source_keys if sk not in pre_merged_source_keys
        ]
        if not survivor_revisions:
            survivor_revisions = surviving_job.revisions

        survivor_cur_rev = select_current_revision(survivor_revisions)
        survivor_first_seen = min(r.first_seen_at for r in survivor_revisions)
        survivor_last_seen = max(r.last_seen_at for r in survivor_revisions)

        updated_survivor = surviving_job.model_copy(
            update={
                "linked_source_keys": survivor_source_keys,
                "revisions": survivor_revisions,
                "current_revision_id": survivor_cur_rev,
                "first_seen_at": survivor_first_seen,
                "last_seen_at": survivor_last_seen,
                "merge_lineage": surviving_job.merge_lineage + [
                    f"REVERSAL: merge op={operation_id} undone by {actor} at {now_iso}: {reason}"
                ],
            }
        )
        canonical_repo.save_canonical_job(updated_survivor)

        # 6. Mark merge event as reversed
        identity_repo.mark_merge_event_reversed(operation_id, reversal_op_id, now)

        return ReversalOperation(
            operation_id=reversal_op_id,
            target_merge_operation_id=operation_id,
            surviving_canonical_id=surviving_id,
            restored_canonical_id=merged_id,
            actor=actor,
            reason=reason,
            reversed_at=now,
        )
