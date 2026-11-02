"""Tests for EVAL-01 paired evaluation adapter."""

from __future__ import annotations

from pathlib import Path

from job_automation.model_benchmarks.evaluation_adapter import (
    run_paired_model_evaluation,
)
from tests.fakes.model_transport import ScriptedModelTransport


class TestEvaluationAdapter:
    def test_run_paired_evaluation_scripted(self, tmp_path: Path) -> None:
        transport = ScriptedModelTransport()
        # Mock responses for any generate calls
        for _ in range(10):
            transport.queue_response(
                "/api/generate",
                200,
                body={"model": "qwen2.5:1.5b", "response": "eligible"},
            )

        eval_dir = tmp_path / "eval_test"
        summary = run_paired_model_evaluation(
            output_dir=eval_dir,
            model_name="qwen2.5:1.5b",
            transport=transport,
            max_cases=2,
        )

        assert summary.total_cases == 2
        assert summary.completed_pairs >= 1
        assert summary.disposition_agreement_rate >= 0.0

