"""Tests for manual text and CSV adapter execution through INGEST-01 PageExecutor (INGEST-01-S03)."""

from pathlib import Path

from job_automation.contracts.enums import AcquisitionMethod
from job_automation.contracts.sources import SourceConfig
from job_automation.ingestion.capture import DurableRawCaptureSink
from job_automation.ingestion.execution import PageExecutor
from job_automation.sources.adapters.manual_csv import ManualCsvAdapter
from job_automation.sources.adapters.manual_text import ManualTextAdapter
from job_automation.sources.validation import validate_source_config

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_MANUAL_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "sources" / "manual"


def _make_manual_source(source_key: str) -> SourceConfig:
    cfg = SourceConfig(
        source_key=source_key,
        provider="manual",
        board_id="local",
        acquisition_method=AcquisitionMethod.MANUAL_IMPORT,
        base_url="https://example.invalid",
        enabled=True,
        access_rules='{"status": "permitted", "reviewed_at": "2026-10-28T00:00:00Z", "evidence_ref": "E-manual"}',
        attribution_rules='{"status": "none_required"}',
    )
    return validate_source_config(cfg)


def test_manual_text_adapter_execution(tmp_path: Path):
    eff = _make_manual_source("manual_txt")
    sink = DurableRawCaptureSink(tmp_path)
    txt_file = _MANUAL_FIXTURES / "text" / "valid_job.txt"

    adapter = ManualTextAdapter(
        effective_source=eff,
        capture_sink=sink,
        source_url="https://example.invalid/jobs/123",
        text_path=txt_file.name,
        input_base_path=txt_file.parent,
    )
    executor = PageExecutor(eff, adapter)
    res = executor.execute_page()

    assert len(res.raw_records) == 1
    assert len(res.draft_results) == 1
    assert res.draft_results[0].draft is not None
    assert res.page.exhausted is True
    assert len(res.parent_refs) >= 1
    assert sink.get(res.parent_refs[0]) is not None


def test_manual_csv_adapter_execution(tmp_path: Path):
    eff = _make_manual_source("manual_csv")
    sink = DurableRawCaptureSink(tmp_path)
    csv_file = _MANUAL_FIXTURES / "csv" / "valid_jobs.csv"

    adapter = ManualCsvAdapter(
        effective_source=eff,
        capture_sink=sink,
        csv_path=csv_file.name,
        input_base_path=csv_file.parent,
        page_size=1,
    )
    executor = PageExecutor(eff, adapter)

    # First page
    res1 = executor.execute_page(continuation=None)
    assert len(res1.raw_records) == 1
    assert len(res1.draft_results) == 1
    assert res1.page.exhausted is False
    assert res1.page.continuation_out is not None

    # Second page
    res2 = executor.execute_page(continuation=res1.page.continuation_out)
    assert len(res2.raw_records) == 1
    assert res2.page.exhausted is True
    assert res2.page.continuation_out is None


def test_manual_csv_bom_handling(tmp_path: Path):
    eff = _make_manual_source("manual_csv_bom")
    sink = DurableRawCaptureSink(tmp_path)
    csv_file = _MANUAL_FIXTURES / "csv" / "bom_jobs.csv"

    adapter = ManualCsvAdapter(
        effective_source=eff,
        capture_sink=sink,
        csv_path=csv_file.name,
        input_base_path=csv_file.parent,
    )
    executor = PageExecutor(eff, adapter)
    res = executor.execute_page()

    assert len(res.raw_records) >= 1
    assert res.page.exhausted is True
