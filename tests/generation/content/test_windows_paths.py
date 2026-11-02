"""Windows path handling for GEN-03: spaces, German umlauts (ä, ö, ü, ß), and non-ASCII paths."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from job_automation.contracts.draft_content import DraftDocumentV2, read_draft_json
from job_automation.generation.input_records import compute_sha256_digest


@pytest.mark.parametrize(
    "folder_name",
    [
        "Bewerbung München Straße 42",
        "Kandidaten Überprüfung Größe äöüß",
        "Job Automation Draft Content Path",
    ],
)
def test_draft_service_and_sqlite_with_special_windows_paths(setup_content, tmp_path: Path, folder_name: str):
    env = setup_content(kind="cv", language="de", strategy="json")
    env.queue()
    result = env.service.generate_content(env.request.request_id)
    assert result.failure is None, result.failure
    assert isinstance(result.draft, DraftDocumentV2)

    # Test storing and reopening from explicit windows path with spaces and umlauts
    special_dir = tmp_path / folder_name / "Unterordner Entwurf ä"
    special_dir.mkdir(parents=True, exist_ok=True)
    content_file = special_dir / "draft_c14_v2_ä.json"
    content_file.write_text(result.draft.model_dump_json(), encoding="utf-8")

    reloaded = read_draft_json(content_file.read_text(encoding="utf-8"))
    assert reloaded == result.draft
    assert compute_sha256_digest(reloaded) == result.receipt.content_hash

