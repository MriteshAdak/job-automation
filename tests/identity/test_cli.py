"""Tests for identity CLI review and merge commands."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from job_automation.cli import main
from job_automation.contracts.postings import NormalizedPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.identity import IdentityService
from job_automation.storage.engine import StorageEngine


def make_config(tmp_path: Path) -> Path:
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
    return cfg_file


def make_norm_posting(
    provider: str,
    posting_id: str,
    title: str,
    desc: str,
) -> NormalizedPosting:
    return NormalizedPosting(
        source_key=SourceKey(provider=provider, board_id="default", source_posting_id=posting_id),
        normalizer_version="1.0-test",
        raw_reference=f"raw/{posting_id}.json",
        raw_content_hash="sha256:" + "0" * 64,
        company_name_hint="CLI Corp GmbH",
        title=title,
        description_clean=desc,
        source_url=f"https://{provider}.example.com/jobs/{posting_id}",
        observed_at=datetime.now(timezone.utc),
    )


class TestIdentityCli:
    def test_cli_review_list_and_decide(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cfg = make_config(tmp_path)
        # Migrate schema first
        assert main(["storage", "migrate", "--config", str(cfg)]) == 0

        # Seed database with a review case
        engine = StorageEngine(db_path=tmp_path / "Runtime Data" / "database" / "job_automation.db")
        service = IdentityService(engine)

        desc = "Software development for scalable APIs."
        p1 = make_norm_posting("src_1", "j1", "API Developer", desc)
        p2 = make_norm_posting("src_2", "j2", "API Developer", desc)
        service.resolve_and_commit(p1)
        res2 = service.resolve_and_commit(p2)
        case_id = res2.review_case_id
        assert case_id is not None
        engine.close()

        # 1. Test review list
        exit_code = main(["identity", "review", "list", "--config", str(cfg)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Identity review cases" in captured.out
        assert case_id in captured.out

        # 2. Test review show
        exit_code = main(["identity", "review", "show", "--case-id", case_id, "--config", str(cfg)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert f"Review Case: {case_id}" in captured.out
        assert "pending" in captured.out

        # 3. Test review decide
        exit_code = main([
            "identity", "review", "decide",
            "--case-id", case_id,
            "--decision", "reject",
            "--actor", "alice",
            "--reason", "Different positions",
            "--config", str(cfg),
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "status=rejected" in captured.out

    def test_cli_merge_and_reverse_merge(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cfg = make_config(tmp_path)
        assert main(["storage", "migrate", "--config", str(cfg)]) == 0

        engine = StorageEngine(db_path=tmp_path / "Runtime Data" / "database" / "job_automation.db")
        service = IdentityService(engine)

        p1 = make_norm_posting("b1", "1", "Dev 1", "Unique text 1")
        p2 = make_norm_posting("b2", "2", "Dev 2", "Unique text 2")
        res1 = service.resolve_and_commit(p1)
        res2 = service.resolve_and_commit(p2)
        id1 = str(res1.canonical_job_id)
        id2 = str(res2.canonical_job_id)
        engine.close()

        # 1. Merge via CLI
        exit_code = main([
            "identity", "merge",
            "--surviving-id", id1,
            "--merged-id", id2,
            "--actor", "bob",
            "--reason", "Manual duplicate confirmation",
            "--config", str(cfg),
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Merge successful: operation_id=" in captured.out

        # Extract operation ID from CLI output
        op_line = [line for line in captured.out.splitlines() if "operation_id=" in line][0]
        op_id = op_line.split("operation_id=")[1].strip()

        # 2. Reverse merge via CLI
        exit_code = main([
            "identity", "reverse-merge",
            "--operation-id", op_id,
            "--actor", "bob",
            "--reason", "Undoing mistaken merge",
            "--config", str(cfg),
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Reversal successful" in captured.out
        assert f"Restored Canonical:  {id2}" in captured.out

