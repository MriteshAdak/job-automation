"""Tests for CLI profile subcommands (import, review, approve, history, show, resolve)."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pytest

from job_automation.cli import main


class TestCliProfile:
    @pytest.fixture
    def app_env(self, tmp_path: Path) -> tuple[Path, Path]:
        cfg_file = tmp_path / "app.json"
        data_dir = (tmp_path / "Runtime Data").resolve()
        cfg_content = {
            "schema_version": "1.0",
            "app_name": "JobAutomation",
            "data_root": str(data_dir),
            "display_timezone": "Europe/Berlin",
            "model_service_url": "http://127.0.0.1:11434",
        }
        cfg_file.write_text(json.dumps(cfg_content), encoding="utf-8")
        return cfg_file, data_dir

    def test_cli_profile_end_to_end_flow(
        self, app_env: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cfg_file, _ = app_env

        # 1. Prepare synthetic input draft
        cid = uuid.uuid4()
        fid = uuid.uuid4()
        draft_file = tmp_path / "synthetic_draft.json"
        draft_payload = {
            "candidate_id": str(cid),
            "proposed_eligibility": {
                "work_authorization_countries": ["DE"],
                "target_locations": ["Berlin"],
                "remote_eligible": True,
            },
            "facts": [
                {
                    "fact_id": str(fid),
                    "title": "Senior Python Developer",
                    "kind": "employment",
                    "claims": ["Designed distributed system"],
                    "skills": ["Python", "SQLite"],
                    "allowed_uses": ["cv", "assessment"],
                }
            ],
            "notes": "Initial candidate profile draft",
        }
        draft_file.write_text(json.dumps(draft_payload), encoding="utf-8")

        # 2. Run 'profile import'
        exit_code = main(["profile", "import", "--input", str(draft_file), "--config", str(cfg_file)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Profile draft imported: SUCCESS" in captured.out
        assert "Status:          UNAPPROVED" in captured.out

        # Extract draft ID and content digest from stdout
        draft_id_match = re.search(r"Draft ID:\s+([a-f0-9\-]+)", captured.out)
        digest_match = re.search(r"Content Digest:\s+([a-f0-9]+)", captured.out)
        assert draft_id_match is not None
        assert digest_match is not None
        draft_id = draft_id_match.group(1)
        digest = digest_match.group(1)

        # 3. Run 'profile review'
        exit_code = main(["profile", "review", "--draft-id", draft_id, "--config", str(cfg_file)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Profile draft review:" in captured.out
        assert "Senior Python Developer" in captured.out

        # 4. Run 'profile approve' with stale digest (should fail)
        exit_code = main([
            "profile", "approve",
            "--draft-id", draft_id,
            "--digest", "bad_digest_hash",
            "--approved-by", "candidate",
            "--config", str(cfg_file),
        ])
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "Profile operation: FAILED" in captured.err

        # 5. Run 'profile approve' with matching digest (should succeed)
        exit_code = main([
            "profile", "approve",
            "--draft-id", draft_id,
            "--digest", digest,
            "--approved-by", "candidate",
            "--config", str(cfg_file),
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Profile publication: SUCCESS" in captured.out
        assert "Profile Version: v1" in captured.out

        # 6. Run 'profile history'
        exit_code = main(["profile", "history", "--config", str(cfg_file)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Profile version history:" in captured.out
        assert "version 'v1' [CURRENT]" in captured.out

        # 7. Run 'profile show' with export
        export_file = tmp_path / "exported_v1.json"
        exit_code = main([
            "profile", "show",
            "--version", "v1",
            "--export", str(export_file),
            "--config", str(cfg_file),
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Profile Snapshot:" in captured.out
        assert export_file.is_file()

        # 8. Run 'profile resolve' for C08 citation
        exit_code = main([
            "profile", "resolve",
            "--version", "v1",
            "--fact-id", str(fid),
            "--config", str(cfg_file),
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "C08 Citation Resolution: SUCCESS" in captured.out
        assert "Senior Python Developer" in captured.out

        # 9. Run 'profile resolve' with nonexistent fact_id (should fail)
        exit_code = main([
            "profile", "resolve",
            "--version", "v1",
            "--fact-id", str(uuid.uuid4()),
            "--config", str(cfg_file),
        ])
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "Profile operation: FAILED" in captured.err

    def test_cli_profile_import_missing_file_fails(
        self, app_env: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        cfg_file, _ = app_env
        exit_code = main([
            "profile", "import",
            "--input", "nonexistent_file.json",
            "--config", str(cfg_file),
        ])
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "Input file not found" in captured.err

