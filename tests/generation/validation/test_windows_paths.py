"""Windows path handling for GEN-04: spaces, German umlauts (ä, ö, ü, ß), and non-ASCII paths."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from job_automation.generation.validation_records import DocumentValidationReport


@pytest.mark.parametrize(
    "folder_name",
    [
        "Bewerbung München Validierung 42",
        "Kandidaten Prüfung Größe äöüß",
        "Job Automation Validation Report Path",
    ],
)
def test_validation_service_with_special_windows_paths(setup_validation, tmp_path: Path, folder_name: str):
    env = setup_validation()
    res = env.validation_service.validate_content(env.request.request_id, env.draft)
    assert res.report is not None
    assert res.report.render_decision == "allowed_for_review"

    # Test storing and reopening report from special windows path with spaces and umlauts
    special_dir = tmp_path / folder_name / "Unterordner Prüfung ä"
    special_dir.mkdir(parents=True, exist_ok=True)
    report_file = special_dir / "report_v1_ä.json"
    report_file.write_text(res.report.model_dump_json(), encoding="utf-8")

    reloaded = DocumentValidationReport.model_validate_json(report_file.read_text(encoding="utf-8"))
    assert reloaded == res.report
    assert reloaded.report_hash == res.report.report_hash

