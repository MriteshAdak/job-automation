"""Native Windows process interruption, handle closure, and resumption verification (INGEST-01-S05, S09).

Spawns child Python processes using sys.executable to simulate:
1. Process 1 starts traversal, fetches page 1, commits page 1 and checkpoint, then exits.
2. Process 2 starts in a new process, reads the checkpoint, resumes from continuation token,
   fetches page 2 (terminal), commits, and finalizes the authoritative C04 manifest.
3. Verifies handle release between processes and complete inventory evidence preserved across restart.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from job_automation.contracts.enums import FetchOutcome
from job_automation.storage.engine import StorageEngine

CHILD_PROCESS_SCRIPT = """
import sys
from pathlib import Path

if len(sys.argv) > 5:
    sys.path.insert(0, sys.argv[5])

import uuid
from datetime import datetime, timezone

from job_automation.contracts.adapter_results import AdapterPage, Continuation
from job_automation.contracts.enums import AcquisitionMethod, FetchOutcome
from job_automation.contracts.postings import RawPosting
from job_automation.contracts.primitives import SourceKey
from job_automation.contracts.sources import SourceConfig
from job_automation.ingestion.controller import FetchController
from job_automation.ingestion.models import ControllerOptions
from job_automation.ingestion.ports import AdapterRegistry
from job_automation.sources.models import SourceRegistryEnvelope
from job_automation.sources.service import SourceRegistryService
from job_automation.sources.validation import validate_source_config
from job_automation.storage.engine import StorageEngine
from tests.fakes.paginated_adapter import ScriptedPaginatedFakeAdapter

mode = sys.argv[1]
db_path = Path(sys.argv[2])
raw_dir = Path(sys.argv[3])
run_id = uuid.UUID(sys.argv[4])

storage = StorageEngine(db_path=db_path, raw_dir=raw_dir)
storage.migrate()

src = SourceConfig(
    source_key="restart_src",
    provider="prov_restart",
    board_id="default",
    acquisition_method=AcquisitionMethod.API,
    base_url="https://restart.invalid/api",
    enabled=True,
    access_rules='{"status": "permitted", "reviewed_at": "2026-10-28T00:00:00Z", "evidence_ref": "E1"}',
    attribution_rules='{"status": "none_required"}',
)
eff = validate_source_config(src)

p = "prov_restart"
b = "default"
cont2 = Continuation(kind="page", value="2", source_key="restart_src", scope_id=f"{p}_{b}", adapter_name="fake")

raw1 = RawPosting(
    raw_payload_ref="raw://p1",
    raw_content_hash="sha256:" + "1" * 64,
    source_key=SourceKey(provider=p, board_id=b, source_posting_id="job_p1"),
    fetch_time=datetime.now(timezone.utc),
    raw_payload='{"id": "job_p1"}',
)
raw2 = RawPosting(
    raw_payload_ref="raw://p2",
    raw_content_hash="sha256:" + "2" * 64,
    source_key=SourceKey(provider=p, board_id=b, source_posting_id="job_p2"),
    fetch_time=datetime.now(timezone.utc),
    raw_payload='{"id": "job_p2"}',
)

page1 = AdapterPage(
    items=[raw1],
    continuation_in=None,
    continuation_out=cont2,
    exhausted=False,
)
page2 = AdapterPage(
    items=[raw2],
    continuation_in=cont2,
    continuation_out=None,
    exhausted=True,
)

adapter = ScriptedPaginatedFakeAdapter(
    pages={None: page1, "2": page2},
    expected_source_key="restart_src",
)

adapter_registry = AdapterRegistry()
adapter_registry.register_for_key("restart_src", lambda s, k, o: adapter)

envelope = SourceRegistryEnvelope(sources=[src])
registry_service = SourceRegistryService.from_envelope(envelope)

if mode == "proc1":
    # Process 1: run with max_pages=1, then exit
    storage.runs.create_run(run_id=run_id)
    options = ControllerOptions(max_pages=1)
    controller = FetchController(
        storage=storage,
        options=options,
        adapter_registry=adapter_registry,
        registry_service=registry_service,
    )
    res = controller.fetch_source(run_id=run_id, effective_source=eff, resume=True)
    assert res.outcome == FetchOutcome.PARTIAL
    assert res.page_count == 1
    storage.close()
    sys.exit(0)

elif mode == "proc2":
    # Process 2: resume traversal to completion
    options = ControllerOptions(max_pages=10)
    controller = FetchController(
        storage=storage,
        options=options,
        adapter_registry=adapter_registry,
        registry_service=registry_service,
    )
    res = controller.fetch_source(run_id=run_id, effective_source=eff, resume=True)
    assert res.outcome == FetchOutcome.COMPLETE
    assert res.manifest.page_count == 2
    assert "job_p1" in res.manifest.observed_posting_identities
    assert "job_p2" in res.manifest.observed_posting_identities
    storage.close()
    sys.exit(0)
    assert res.page_count == 2
    assert "job_p1" in res.manifest.observed_posting_identities
    assert "job_p2" in res.manifest.observed_posting_identities
    storage.close()
    sys.exit(0)
"""


def test_windows_process_restart_and_resumption(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent.parent.parent
    db_path = tmp_path / "restart_data" / "restart.db"
    raw_dir = tmp_path / "restart_data" / "raw"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    run_id = uuid.uuid4()

    # Step 1: Run Process 1
    p1 = subprocess.run(
        [
            sys.executable,
            "-c",
            CHILD_PROCESS_SCRIPT,
            "proc1",
            str(db_path),
            str(raw_dir),
            str(run_id),
            str(repo_root),
        ],
        capture_output=True,
        text=True,
    )
    assert p1.returncode == 0, f"Process 1 failed with stdout: {p1.stdout}\nstderr: {p1.stderr}"

    # Step 2: Run Process 2 in a separate child process to resume
    p2 = subprocess.run(
        [
            sys.executable,
            "-c",
            CHILD_PROCESS_SCRIPT,
            "proc2",
            str(db_path),
            str(raw_dir),
            str(run_id),
            str(repo_root),
        ],
        capture_output=True,
        text=True,
    )
    assert p2.returncode == 0, f"Process 2 failed with stdout: {p2.stdout}\nstderr: {p2.stderr}"

    # Step 3: Verify the persisted state in storage
    storage = StorageEngine(db_path=db_path, raw_dir=raw_dir)
    manifests = storage.raw_postings.get_manifests_for_run(run_id)
    assert len(manifests) == 1
    m = manifests[0]
    assert m.outcome == FetchOutcome.COMPLETE
    assert m.page_count == 2
    assert "job_p1" in m.observed_posting_identities
    assert "job_p2" in m.observed_posting_identities
    storage.close()
