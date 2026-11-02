"""Native Windows path testing with spaces, German umlauts, and handle release."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.identity import IdentityService
from job_automation.storage.engine import StorageEngine


class TestWindowsPaths:
    def test_unicode_and_spaced_paths(self, tmp_path: Path) -> None:
        """Database on Windows path with spaces and German umlauts (äöüß)."""
        unicode_dir = tmp_path / "Identität Prüfung äöü & Leerzeichen"
        unicode_dir.mkdir(parents=True, exist_ok=True)
        db_path = unicode_dir / "Job Suche Identität.db"

        # 1. Initialize and run operations
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()
            service = IdentityService(engine)

            np = NormalizedPosting(
                source_key=SourceKey(provider="manual", board_id="berlin", source_posting_id="p_win_1"),
                normalizer_version="1.0-win",
                raw_reference="raw/win1.json",
                raw_content_hash="sha256:" + "0" * 64,
                company_name_hint="Bayerische Motoren Werke AG",
                title="Spezialist Softwareentwicklung (m/w/d)",
                description_clean="Entwicklung von eingebetteten Systemen und Steuergeräten.",
                source_url="https://example.com/bmw/1",
                observed_at=datetime.now(timezone.utc),
            )
            res = service.resolve_and_commit(np)
            can_id = res.canonical_job_id

        # 2. File handle release verification: file can be opened and reopened cleanly
        assert db_path.exists()
        assert db_path.stat().st_size > 0

        # 3. Re-open database from another StorageEngine instance and verify data integrity
        with StorageEngine(db_path=db_path) as engine_reopen:
            job = engine_reopen.canonical_jobs.get_canonical_job(can_id)
            assert job is not None
            assert job.company_name == "Bayerische Motoren Werke AG"
            assert len(job.revisions) == 1
            assert job.revisions[0].title == "Spezialist Softwareentwicklung (m/w/d)"

