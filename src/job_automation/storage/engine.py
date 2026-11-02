"""StorageEngine facade coordinating connection, migrations, filestore, and repositories."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from job_automation.configuration import AppConfig, ResolvedPaths
from job_automation.storage.connection import open_connection, transaction
from job_automation.storage.filestore import Filestore
from job_automation.storage.migrations import (
    apply_migrations,
    get_current_schema_version,
)
from job_automation.storage.repositories.artifacts import ArtifactRepository
from job_automation.storage.repositories.assessments import AssessmentRepository
from job_automation.storage.repositories.availability import AvailabilityRepository
from job_automation.storage.repositories.canonical_jobs import CanonicalJobRepository
from job_automation.storage.repositories.context_indexes import ContextIndexRepository
from job_automation.storage.repositories.generation_requests import GenerationRequestRepository
from job_automation.storage.repositories.generation_work import GenerationWorkRepository
from job_automation.storage.repositories.generation_inputs import GenerationInputRepository
from job_automation.storage.repositories.draft_content import DraftContentRepository
from job_automation.storage.repositories.document_validations import DocumentValidationRepository
from job_automation.storage.repositories.render_artifacts import RenderArtifactRepository
from job_automation.storage.repositories.artifact_deliveries import ArtifactDeliveryRepository
from job_automation.storage.repositories.identity import IdentityRepository
from job_automation.storage.repositories.profiles import ProfileRepository
from job_automation.storage.repositories.raw_postings import RawPostingRepository
from job_automation.storage.repositories.runs import RunLedgerRepository
from job_automation.storage.repositories.sync_outbox import SyncOutboxRepository
from job_automation.storage.repositories.sync_state import SyncStateRepository
from job_automation.storage.repositories.candidate_snapshots import CandidateSnapshotRepository
from job_automation.storage.repositories.pipeline_work import PipelineWorkRepository
from job_automation.storage.repositories.operations import OperationsRepository
from job_automation.storage.repositories.scheduling import SchedulingRepository
from job_automation.storage.repositories.automatic_drafts import AutomaticDraftRepository
from job_automation.storage.repositories.run_summary_deliveries import RunSummaryDeliveryRepository


class StorageEngine:
    """Central entry point for all durable local storage operations.

    Owns:
    - SQLite database connection, PRAGMA configuration, and transaction lifecycle.
    - Schema migrations and version verification.
    - Filesystem storage for raw payloads and binary artifacts.
    - Typed contract repositories for runs, raw postings, canonical jobs,
      assessments, sync outbox, generation requests, and artifacts.
    """

    def __init__(
        self,
        db_path: Path | str,
        raw_dir: Path | str | None = None,
        artifacts_dir: Path | str | None = None,
        profiles_dir: Path | str | None = None,
        indexes_dir: Path | str | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.db_path = Path(db_path)
        self.raw_dir = Path(raw_dir) if raw_dir else self.db_path.parent.parent / "raw"
        self.artifacts_dir = (
            Path(artifacts_dir)
            if artifacts_dir
            else self.db_path.parent.parent / "artifacts"
        )
        self.profiles_dir = (
            Path(profiles_dir)
            if profiles_dir
            else self.db_path.parent.parent / "profiles"
        )
        self.indexes_dir = (
            Path(indexes_dir)
            if indexes_dir
            else self.db_path.parent.parent / "indexes"
        )
        self.timeout = timeout

        self._conn: sqlite3.Connection | None = None
        self._canonical_jobs: CanonicalJobRepository | None = None
        self._identity: IdentityRepository | None = None
        self._availability: AvailabilityRepository | None = None
        self.filestore = Filestore(raw_dir=self.raw_dir, artifacts_dir=self.artifacts_dir)

    @classmethod
    def from_config(
        cls,
        config: AppConfig,
        paths: ResolvedPaths | None = None,
    ) -> StorageEngine:
        """Create StorageEngine from application configuration and resolved paths."""
        resolved = paths or config.resolve_paths()
        return cls(
            db_path=resolved.database_path,
            raw_dir=resolved.raw_dir,
            artifacts_dir=resolved.artifacts_dir,
            profiles_dir=resolved.profiles_dir,
            indexes_dir=resolved.indexes_dir,
        )

    @property
    def conn(self) -> sqlite3.Connection:
        """Lazy-initialized database connection."""
        if self._conn is None:
            self._conn = open_connection(self.db_path, timeout=self.timeout)
        return self._conn

    def close(self) -> None:
        """Close open database connection and release file locks."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            self._canonical_jobs = None
            self._identity = None
            self._availability = None

    def __enter__(self) -> StorageEngine:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()

    def migrate(self, target_version: int | None = None) -> list[int]:
        """Apply unapplied schema migrations sequentially."""
        return apply_migrations(self.conn, target_version=target_version)

    def initialize_schema(self) -> list[int]:
        """Convenience method to ensure schema migrations are applied."""
        return self.migrate()

    def get_schema_version(self) -> int:
        """Return the current applied schema migration version."""
        return get_current_schema_version(self.conn)

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for atomic multi-repository operations."""
        with transaction(self.conn) as conn:
            yield conn

    # Repositories
    @property
    def runs(self) -> RunLedgerRepository:
        return RunLedgerRepository(self.conn)

    @property
    def raw_postings(self) -> RawPostingRepository:
        return RawPostingRepository(self.conn, filestore=self.filestore)

    @property
    def canonical_jobs(self) -> CanonicalJobRepository:
        if self._canonical_jobs is None:
            self._canonical_jobs = CanonicalJobRepository(self.conn)
        return self._canonical_jobs

    @property
    def identity(self) -> IdentityRepository:
        if self._identity is None:
            self._identity = IdentityRepository(self.conn)
        return self._identity

    @property
    def availability(self) -> AvailabilityRepository:
        if self._availability is None:
            self._availability = AvailabilityRepository(self.conn)
        return self._availability

    @property
    def assessments(self) -> AssessmentRepository:
        return AssessmentRepository(self.conn)

    @property
    def sync_outbox(self) -> SyncOutboxRepository:
        return SyncOutboxRepository(self.conn)

    @property
    def sync_state(self) -> SyncStateRepository:
        return SyncStateRepository(self.conn)

    @property
    def candidate_snapshots(self) -> CandidateSnapshotRepository:
        return CandidateSnapshotRepository(self.conn)

    @property
    def profiles(self) -> ProfileRepository:
        return ProfileRepository(self.conn)

    @property
    def generation_requests(self) -> GenerationRequestRepository:
        return GenerationRequestRepository(self.conn)

    @property
    def generation_work(self) -> GenerationWorkRepository:
        return GenerationWorkRepository(self.conn)

    @property
    def generation_inputs(self) -> GenerationInputRepository:
        return GenerationInputRepository(self.conn)

    @property
    def draft_content(self) -> DraftContentRepository:
        return DraftContentRepository(self.conn)

    @property
    def artifacts(self) -> ArtifactRepository:
        return ArtifactRepository(self.conn)

    @property
    def context_indexes(self) -> ContextIndexRepository:
        return ContextIndexRepository(self.conn)

    @property
    def pipeline_work(self) -> PipelineWorkRepository:
        return PipelineWorkRepository(self.conn)

    @property
    def operations(self) -> OperationsRepository:
        return OperationsRepository(self.conn)

    @property
    def document_validations(self) -> DocumentValidationRepository:
        return DocumentValidationRepository(self.conn)

    @property
    def render_artifacts(self) -> RenderArtifactRepository:
        return RenderArtifactRepository(self.conn)

    @property
    def artifact_deliveries(self) -> ArtifactDeliveryRepository:
        return ArtifactDeliveryRepository(self.conn)

    @property
    def scheduling(self) -> SchedulingRepository:
        return SchedulingRepository(self.conn)

    @property
    def automatic_drafts(self) -> AutomaticDraftRepository:
        return AutomaticDraftRepository(self.conn)

    @property
    def summary_deliveries(self) -> RunSummaryDeliveryRepository:
        return RunSummaryDeliveryRepository(self.conn)

