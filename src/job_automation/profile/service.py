"""Central ProfileService orchestrating intake, approval, inclusion, history, and C08 resolution."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

from job_automation.configuration import AppConfig, ResolvedPaths
from job_automation.contracts.evidence import CandidateEvidenceReference
from job_automation.contracts.profile import CandidateFact, ProfileSnapshot
from job_automation.profile.approval import approve_draft_to_snapshot
from job_automation.profile.errors import ProfileNotFoundError
from job_automation.profile.evidence_store import EvidenceStore
from job_automation.profile.history import compare_snapshots, list_version_history
from job_automation.profile.inclusion import InclusionRules
from job_automation.profile.intake import parse_draft_intake
from job_automation.profile.models import (
    DEFAULT_RULE_VERSION,
    DraftProfile,
    ProfileDiff,
    ProfileInclusionView,
    ProfileVersionRecord,
    ProvenanceRecord,
)
from job_automation.profile.references import resolve_candidate_evidence_reference

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine
    from job_automation.storage.repositories.profiles import ProfileRepository


class ProfileService:
    """Service facade for candidate profile operations."""

    def __init__(
        self,
        repository: ProfileRepository,
        evidence_store: EvidenceStore,
        rule_version: str = DEFAULT_RULE_VERSION,
    ) -> None:
        self.repo = repository
        self.evidence_store = evidence_store
        self.inclusion_rules = InclusionRules(rule_version=rule_version)

    @classmethod
    def from_engine(
        cls,
        engine: StorageEngine,
        rule_version: str = DEFAULT_RULE_VERSION,
    ) -> ProfileService:
        """Construct ProfileService from StorageEngine."""
        ev_store = EvidenceStore(profiles_dir=engine.profiles_dir)
        return cls(
            repository=engine.profiles,
            evidence_store=ev_store,
            rule_version=rule_version,
        )

    @classmethod
    def from_config(
        cls,
        config: AppConfig,
        paths: ResolvedPaths | None = None,
        rule_version: str = DEFAULT_RULE_VERSION,
    ) -> ProfileService:
        """Construct ProfileService from application configuration."""
        from job_automation.storage.engine import StorageEngine

        resolved = paths or config.resolve_paths()
        engine = StorageEngine.from_config(config, resolved)
        return cls.from_engine(engine, rule_version=rule_version)

    # -----------------------------------------------------------------------
    # Intake & Drafts
    # -----------------------------------------------------------------------

    def import_draft(
        self,
        data: dict[str, Any] | str,
        candidate_id: uuid.UUID | None = None,
    ) -> DraftProfile:
        """Parse, validate, and persist an unapproved draft profile."""
        draft = parse_draft_intake(data, candidate_id_override=candidate_id)
        self.repo.save_draft(draft)
        return draft

    def get_draft(self, draft_id: uuid.UUID) -> DraftProfile:
        """Retrieve an unapproved draft by ID."""
        draft = self.repo.get_draft(draft_id)
        if draft is None:
            raise ProfileNotFoundError(f"Draft '{draft_id}' not found")
        return draft

    def list_drafts(self, candidate_id: uuid.UUID | None = None) -> list[DraftProfile]:
        """List all unapproved drafts."""
        return self.repo.list_drafts(candidate_id)

    # -----------------------------------------------------------------------
    # Approval & Publication
    # -----------------------------------------------------------------------

    def approve_and_publish(
        self,
        draft_id: uuid.UUID,
        expected_draft_digest: str,
        approved_by: str,
        notes: str | None = None,
        expected_base_version: str | None = None,
        version_override: str | None = None,
    ) -> ProfileSnapshot:
        """Validate review digest and publish immutable C01 ProfileSnapshot."""
        draft = self.get_draft(draft_id)

        history = self.repo.get_version_history(draft.candidate_id)
        predecessor_ver = self.repo.get_current_version(draft.candidate_id)

        if history:
            next_seq = max(h.version_sequence for h in history) + 1
        else:
            next_seq = 1

        new_version = version_override or f"v{next_seq}"

        snapshot, content_hash = approve_draft_to_snapshot(
            draft=draft,
            expected_draft_digest=expected_draft_digest,
            approved_by=approved_by,
            new_version=new_version,
            notes=notes,
            expected_base_version=expected_base_version,
        )

        self.repo.publish_snapshot(
            snapshot=snapshot,
            version_sequence=next_seq,
            predecessor_version=predecessor_ver,
            content_hash=content_hash,
            approved_by=approved_by,
            approved_at=snapshot.approval_metadata.approved_at,
            notes=notes,
            is_current=True,
        )

        # Clean up draft now that it has been approved
        self.repo.delete_draft(draft_id)
        return snapshot

    # -----------------------------------------------------------------------
    # Snapshots & Inclusion
    # -----------------------------------------------------------------------

    def get_snapshot(self, version: str) -> ProfileSnapshot:
        """Retrieve an approved snapshot by version."""
        snapshot = self.repo.get_snapshot(version)
        if snapshot is None:
            raise ProfileNotFoundError(f"Profile version '{version}' not found")
        return snapshot

    def get_current_snapshot(self, candidate_id: uuid.UUID | None = None) -> ProfileSnapshot | None:
        """Retrieve the current active approved snapshot."""
        return self.repo.get_current_snapshot(candidate_id)

    def get_inclusion_view(
        self,
        version_or_snapshot: str | ProfileSnapshot,
        purpose: str,
        mandatory_fact_ids: Sequence[uuid.UUID] | None = None,
    ) -> ProfileInclusionView:
        """Obtain a purpose-filtered view of candidate evidence."""
        if isinstance(version_or_snapshot, str):
            snapshot = self.get_snapshot(version_or_snapshot)
        else:
            snapshot = version_or_snapshot

        return self.inclusion_rules.evaluate_inclusion(
            snapshot=snapshot,
            purpose=purpose,
            mandatory_fact_ids=mandatory_fact_ids,
        )

    # -----------------------------------------------------------------------
    # Exact C08 Resolution
    # -----------------------------------------------------------------------

    def resolve_candidate_reference(
        self,
        reference: CandidateEvidenceReference | dict[str, Any] | tuple[str, uuid.UUID],
    ) -> CandidateFact:
        """Resolve a candidate evidence citation to the exact historical fact in that version."""
        return resolve_candidate_evidence_reference(self.repo, reference)

    # -----------------------------------------------------------------------
    # History & Diffing
    # -----------------------------------------------------------------------

    def list_history(self, candidate_id: uuid.UUID | None = None) -> list[ProfileVersionRecord]:
        """List published version records in chronological sequence."""
        return list_version_history(self.repo, candidate_id)

    def diff_versions(self, base_version: str, target_version: str) -> ProfileDiff:
        """Compute structural differences between two published versions."""
        base_snap = self.get_snapshot(base_version)
        target_snap = self.get_snapshot(target_version)
        return compare_snapshots(base_snap, target_snap)
