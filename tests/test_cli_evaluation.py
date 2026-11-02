"""Tests for evaluation CLI commands and dispatch (EVAL-01-S08)."""

import json
from pathlib import Path
import subprocess
import sys
import uuid
import pytest

from job_automation.cli import create_parser, main


def test_cli_parser_evaluation_subcommands():
    """Verify evaluation subcommands are properly registered in CLI parser."""
    parser = create_parser()

    # check
    args = parser.parse_args(["evaluation", "check", "--eval-root", "C:\\test_root"])
    assert args.command == "evaluation"
    assert args.eval_command == "check"
    assert args.eval_root == "C:\\test_root"

    # run
    args = parser.parse_args(["evaluation", "run", "--eval-root", "C:\\test_root", "--split", "development"])
    assert args.eval_command == "run"
    assert args.split == "development"

    # resume
    uid = str(uuid.uuid4())
    args = parser.parse_args(["evaluation", "resume", "--eval-root", "C:\\test_root", "--experiment-id", uid])
    assert args.eval_command == "resume"
    assert args.experiment_id == uid

    # sample-rejects
    args = parser.parse_args(["evaluation", "sample-rejects", "--output", "sample.json"])
    assert args.eval_command == "sample-rejects"
    assert args.output == "sample.json"


def test_cli_check_command_execution(tmp_path: Path):
    """Test executing 'evaluation check' via CLI runner."""
    eval_dir = (tmp_path / "cli_check_dir").resolve()
    eval_dir.mkdir(parents=True, exist_ok=True)

    parser = create_parser()
    args = parser.parse_args(["evaluation", "check", "--eval-root", str(eval_dir)])

    from job_automation.evaluation.cli import handle_evaluation_commands
    ret = handle_evaluation_commands(args)
    assert ret == 0


def test_cli_sample_rejects_command_execution(tmp_path: Path):
    """Test executing 'evaluation sample-rejects' via CLI runner."""
    out_file = (tmp_path / "sample_manifest.json").resolve()
    parser = create_parser()
    args = parser.parse_args([
        "evaluation", "sample-rejects",
        "--sample-size", "5",
        "--seed", "101",
        "--output", str(out_file),
    ])

    from job_automation.evaluation.cli import handle_evaluation_commands
    ret = handle_evaluation_commands(args)
    assert ret == 0
    assert out_file.exists()

    with open(out_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["sample_size"] > 0
    assert "inclusion_probabilities" in data

