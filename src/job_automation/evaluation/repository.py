"""Isolated SQLite repository for evaluation records (EVAL-01-S03).

Enforces:
- Atomicity and WAL concurrency.
- Storage in dedicated eval tables; zero interaction with production tables.
- Complete round-trip serialization of cases, manifests, pairs, corrections, and reports.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import uuid
from typing import Any

from job_automation.evaluation.migrations import initialize_evaluation_migrations
from job_automation.evaluation.records import (
    ArmAttempt,
    EvaluationCase,
    ExperimentManifest,
    MetricReport,
    PairResult,
    ReviewCorrection,
    SampleManifest,
)
from job_automation.storage.connection import open_connection, transaction


class EvaluationRepository:
    """Dedicated persistence repository for evaluation artifacts."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path).resolve()
        self.conn = open_connection(self.db_path)
        self.initialize_schema()

    def initialize_schema(self) -> int:
        """Run evaluation schema migrations."""
        return initialize_evaluation_migrations(self.conn)

    def close(self) -> None:
        """Close SQLite database connection."""
        self.conn.close()

    # --- Experiments ---

    def save_experiment(self, manifest: ExperimentManifest, status: str = "running") -> None:
        """Upsert experiment manifest."""
        manifest_json = manifest.model_dump_json()
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO eval_experiments (
                    experiment_id, experiment_name, corpus_version, split_name,
                    manifest_json, manifest_fingerprint, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id) DO UPDATE SET
                    status = excluded.status,
                    manifest_json = excluded.manifest_json
                """,
                (
                    str(manifest.experiment_id),
                    manifest.experiment_name,
                    manifest.corpus_version,
                    manifest.split_name,
                    manifest_json,
                    manifest.manifest_fingerprint,
                    status,
                    manifest.created_at.isoformat(),
                ),
            )

    def update_experiment_status(self, experiment_id: uuid.UUID, status: str) -> None:
        """Update execution status of experiment."""
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE eval_experiments SET status = ? WHERE experiment_id = ?",
                (status, str(experiment_id)),
            )

    def get_experiment(self, experiment_id: uuid.UUID) -> ExperimentManifest | None:
        """Retrieve experiment manifest by ID."""
        cursor = self.conn.execute(
            "SELECT manifest_json FROM eval_experiments WHERE experiment_id = ?",
            (str(experiment_id),),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return ExperimentManifest.model_validate_json(row["manifest_json"])

    def list_experiments(self) -> list[dict[str, Any]]:
        """List summary of all persisted experiments."""
        cursor = self.conn.execute(
            "SELECT experiment_id, experiment_name, corpus_version, split_name, status, created_at FROM eval_experiments ORDER BY created_at DESC"
        )
        return [dict(row) for row in cursor.fetchall()]

    # --- Cases ---

    def save_case(self, case: EvaluationCase) -> None:
        """Save evaluation case."""
        case_json = case.model_dump_json()
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO eval_cases (
                    case_id, canonical_job_id, posting_revision,
                    opportunity_group_id, split_assignment, case_json, case_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    case_json = excluded.case_json,
                    case_fingerprint = excluded.case_fingerprint
                """,
                (
                    case.case_id,
                    str(case.canonical_job_id),
                    case.posting_revision,
                    case.opportunity_group_id,
                    case.split_assignment,
                    case_json,
                    case.case_fingerprint,
                ),
            )

    def get_case(self, case_id: str) -> EvaluationCase | None:
        """Retrieve evaluation case by ID."""
        cursor = self.conn.execute(
            "SELECT case_json FROM eval_cases WHERE case_id = ?",
            (case_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return EvaluationCase.model_validate_json(row["case_json"])

    # --- Pairs and Arm Attempts ---

    def save_pair_result(self, pair: PairResult) -> None:
        """Save paired comparison result and its constituent arm attempts."""
        pair_json = pair.model_dump_json()
        order_str = ",".join(s.value for s in pair.execution_order)
        with transaction(self.conn):
            # Clean up prior pair attempts if pair_id changed across restarts
            self.conn.execute(
                """
                DELETE FROM eval_arm_attempts WHERE pair_id IN (
                    SELECT pair_id FROM eval_pairs
                    WHERE experiment_id = ? AND case_id = ? AND repetition_index = ? AND pair_id != ?
                )
                """,
                (str(pair.experiment_id), pair.case_id, pair.repetition_index, str(pair.pair_id)),
            )
            self.conn.execute(
                """
                DELETE FROM eval_pairs
                WHERE experiment_id = ? AND case_id = ? AND repetition_index = ? AND pair_id != ?
                """,
                (str(pair.experiment_id), pair.case_id, pair.repetition_index, str(pair.pair_id)),
            )

            self.conn.execute(
                """
                INSERT INTO eval_pairs (
                    pair_id, experiment_id, case_id, repetition_index,
                    execution_order, baseline_disposition, pair_completed,
                    strategy_delta_score, disposition_agreement, pair_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pair_id) DO UPDATE SET
                    pair_completed = excluded.pair_completed,
                    strategy_delta_score = excluded.strategy_delta_score,
                    disposition_agreement = excluded.disposition_agreement,
                    pair_json = excluded.pair_json
                """,
                (
                    str(pair.pair_id),
                    str(pair.experiment_id),
                    pair.case_id,
                    pair.repetition_index,
                    order_str,
                    pair.baseline_disposition.value,
                    1 if pair.pair_completed else 0,
                    pair.strategy_delta_score,
                    1 if pair.disposition_agreement else (0 if pair.disposition_agreement is False else None),
                    pair_json,
                ),
            )

            # Persist individual arm attempts
            for arm in (pair.json_arm, pair.rag_arm):
                self._save_arm_attempt_internal(arm)

    def _save_arm_attempt_internal(self, arm: ArmAttempt) -> None:
        attempt_json = arm.model_dump_json()
        disp = arm.final_assessment.final_disposition.value if arm.final_assessment else None
        score = arm.final_assessment.relevance_score if arm.final_assessment else None
        self.conn.execute(
            """
            INSERT INTO eval_arm_attempts (
                attempt_id, pair_id, case_id, strategy, repetition_index,
                execution_status, disposition, relevance_score,
                stage_latencies_json, token_counts_json, attempt_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(attempt_id) DO UPDATE SET
                execution_status = excluded.execution_status,
                disposition = excluded.disposition,
                relevance_score = excluded.relevance_score,
                attempt_json = excluded.attempt_json
            """,
            (
                str(arm.attempt_id),
                str(arm.pair_id),
                arm.case_id,
                arm.strategy.value,
                arm.repetition_index,
                arm.execution_status,
                disp,
                score,
                json.dumps(arm.stage_latencies_ms),
                json.dumps(arm.token_counts),
                attempt_json,
                arm.started_at.isoformat(),
            ),
        )

    def get_pair_result(self, pair_id: uuid.UUID) -> PairResult | None:
        """Retrieve pair result by ID."""
        cursor = self.conn.execute(
            "SELECT pair_json FROM eval_pairs WHERE pair_id = ?",
            (str(pair_id),),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return PairResult.model_validate_json(row["pair_json"])

    def get_pair_for_case(
        self,
        experiment_id: uuid.UUID,
        case_id: str,
        repetition_index: int = 0,
    ) -> PairResult | None:
        """Retrieve pair result for specific experiment, case, and repetition index."""
        cursor = self.conn.execute(
            """
            SELECT pair_json FROM eval_pairs
            WHERE experiment_id = ? AND case_id = ? AND repetition_index = ?
            """,
            (str(experiment_id), case_id, repetition_index),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return PairResult.model_validate_json(row["pair_json"])

    def list_pairs_for_experiment(self, experiment_id: uuid.UUID) -> list[PairResult]:
        """List all pairs recorded for an experiment."""
        cursor = self.conn.execute(
            "SELECT pair_json FROM eval_pairs WHERE experiment_id = ?",
            (str(experiment_id),),
        )
        return [PairResult.model_validate_json(row["pair_json"]) for row in cursor.fetchall()]

    # --- Review Corrections ---

    def save_correction(self, correction: ReviewCorrection) -> None:
        """Save human review correction."""
        correction_json = correction.model_dump_json()
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO eval_corrections (
                    correction_id, case_id, arm_id, reviewer_id, target_type,
                    old_value_json, new_value_json, reason, active_review_seconds,
                    adjudication_status, correction_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(correction_id) DO UPDATE SET
                    adjudication_status = excluded.adjudication_status,
                    correction_json = excluded.correction_json
                """,
                (
                    str(correction.correction_id),
                    correction.case_id,
                    str(correction.arm_id) if correction.arm_id else None,
                    correction.reviewer_id,
                    correction.target_type,
                    json.dumps(correction.old_value),
                    json.dumps(correction.new_value),
                    correction.reason,
                    correction.active_review_seconds,
                    correction.adjudication_status,
                    correction_json,
                    correction.timestamp.isoformat(),
                ),
            )

    def list_corrections(self, case_id: str | None = None) -> list[ReviewCorrection]:
        """List all recorded corrections, optionally filtered by case_id."""
        if case_id is not None:
            cursor = self.conn.execute(
                "SELECT correction_json FROM eval_corrections WHERE case_id = ? ORDER BY created_at ASC",
                (case_id,),
            )
        else:
            cursor = self.conn.execute(
                "SELECT correction_json FROM eval_corrections ORDER BY created_at ASC"
            )
        return [ReviewCorrection.model_validate_json(row["correction_json"]) for row in cursor.fetchall()]

    # --- Sampling ---

    def save_sample_manifest(self, sample: SampleManifest) -> None:
        """Save rejected-job sample manifest."""
        sample_json = sample.model_dump_json()
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO eval_samples (
                    sample_id, population_cohort_id, population_size,
                    sample_size, sampling_seed, frame_hash, sample_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sample_id) DO UPDATE SET
                    sample_json = excluded.sample_json
                """,
                (
                    str(sample.sample_id),
                    sample.population_cohort_id,
                    sample.population_size,
                    sample.sample_size,
                    sample.sampling_seed,
                    sample.frame_hash,
                    sample_json,
                    sample.created_at.isoformat(),
                ),
            )

    def get_sample_manifest(self, sample_id: uuid.UUID) -> SampleManifest | None:
        """Retrieve sample manifest by ID."""
        cursor = self.conn.execute(
            "SELECT sample_json FROM eval_samples WHERE sample_id = ?",
            (str(sample_id),),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return SampleManifest.model_validate_json(row["sample_json"])

    # --- Metric Reports ---

    def save_report(self, report: MetricReport) -> None:
        """Save comprehensive evaluation metric report."""
        report_json = report.model_dump_json()
        with transaction(self.conn):
            self.conn.execute(
                """
                INSERT INTO eval_reports (
                    report_id, experiment_id, generated_at, total_cases,
                    completed_pairs, report_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(report_id) DO UPDATE SET
                    report_json = excluded.report_json
                """,
                (
                    str(report.report_id),
                    str(report.experiment_id),
                    report.generated_at.isoformat(),
                    report.total_cases,
                    report.completed_pairs,
                    report_json,
                ),
            )

    def get_report(self, report_id: uuid.UUID) -> MetricReport | None:
        """Retrieve metric report by report ID."""
        cursor = self.conn.execute(
            "SELECT report_json FROM eval_reports WHERE report_id = ?",
            (str(report_id),),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return MetricReport.model_validate_json(row["report_json"])

    def get_latest_report(self, experiment_id: uuid.UUID) -> MetricReport | None:
        """Retrieve most recently generated report for an experiment."""
        cursor = self.conn.execute(
            """
            SELECT report_json FROM eval_reports
            WHERE experiment_id = ?
            ORDER BY generated_at DESC LIMIT 1
            """,
            (str(experiment_id),),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return MetricReport.model_validate_json(row["report_json"])

    save_metric_report = save_report
    get_metric_report = get_latest_report
