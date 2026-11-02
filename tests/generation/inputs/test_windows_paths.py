"""Native Windows path compatibility tests with spaces, non-ASCII German characters, and pathlib."""

from __future__ import annotations

from pathlib import Path

from job_automation.contracts.enums import ContextStrategy
from job_automation.generation.input_service import DefaultGenerationInputService
from job_automation.storage.engine import StorageEngine
from tests.generation.inputs.conftest import (
    create_job_with_posting,
    make_request,
    publish_approved_profile,
)


class TestWindowsPaths:
    def test_windows_paths_with_spaces_and_german_umlauts(self, tmp_path: Path) -> None:
        """Verify storage engine and input service function with German umlauts and spaces in paths."""
        win_dir = tmp_path / "Bewerbung München Straße 42" / "Größe Daten"
        win_dir.mkdir(parents=True, exist_ok=True)

        engine = StorageEngine(
            db_path=win_dir / "Datenbank äöüß.db",
            raw_dir=win_dir / "Rohe Daten",
            artifacts_dir=win_dir / "Artefakte",
            profiles_dir=win_dir / "Profile",
            indexes_dir=win_dir / "Indexe",
        )
        engine.initialize_schema()

        job, _, _ = create_job_with_posting(engine, title="Softwareentwickler München")
        profile = publish_approved_profile(engine)

        service = DefaultGenerationInputService(engine=engine)
        req = make_request(job_id=job.canonical_job_id, strategy=ContextStrategy.JSON)
        engine.generation_requests.create_request(req)

        # Prepare freeze
        manifest, err = service.prepare_freeze(req, f"freeze:{req.request_id}")
        assert err is None
        assert manifest is not None

        # Build context
        bundle, ctx_err = service.build_context(manifest, f"ctx:{req.request_id}")
        assert ctx_err is None
        assert bundle is not None
        assert bundle.posting_revision == job.revisions[0].content_hash

        # Verify inspection succeeds
        receipt = service.inspect_preflight(req.request_id)
        assert receipt is not None
        assert receipt.result == "prepared"

        engine.close()

