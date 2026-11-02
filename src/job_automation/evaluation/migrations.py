"""Dedicated SQLite migrations for isolated evaluation storage (EVAL-01-S03).

Enforces:
- Independent migration ledger: eval_schema_migrations.
- Zero references to production tables.
- Tables for experiments, cases, pairs, arm attempts, review corrections, samples, and reports.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Callable


MigrationFn = Callable[[sqlite3.Connection], None]


def _migration_001_initial_evaluation_schema(conn: sqlite3.Connection) -> None:
    """Create initial evaluation tables."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS eval_experiments (
        experiment_id TEXT PRIMARY KEY,
        experiment_name TEXT NOT NULL,
        corpus_version TEXT NOT NULL,
        split_name TEXT NOT NULL,
        manifest_json TEXT NOT NULL,
        manifest_fingerprint TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS eval_cases (
        case_id TEXT PRIMARY KEY,
        canonical_job_id TEXT NOT NULL,
        posting_revision TEXT NOT NULL,
        opportunity_group_id TEXT NOT NULL,
        split_assignment TEXT NOT NULL,
        case_json TEXT NOT NULL,
        case_fingerprint TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS eval_pairs (
        pair_id TEXT PRIMARY KEY,
        experiment_id TEXT NOT NULL,
        case_id TEXT NOT NULL,
        repetition_index INTEGER NOT NULL,
        execution_order TEXT NOT NULL,
        baseline_disposition TEXT NOT NULL,
        pair_completed INTEGER NOT NULL,
        strategy_delta_score REAL,
        disposition_agreement INTEGER,
        pair_json TEXT NOT NULL,
        FOREIGN KEY (experiment_id) REFERENCES eval_experiments(experiment_id),
        UNIQUE (experiment_id, case_id, repetition_index)
    );

    CREATE INDEX IF NOT EXISTS idx_eval_pairs_exp_case
    ON eval_pairs(experiment_id, case_id);

    CREATE TABLE IF NOT EXISTS eval_arm_attempts (
        attempt_id TEXT PRIMARY KEY,
        pair_id TEXT NOT NULL,
        case_id TEXT NOT NULL,
        strategy TEXT NOT NULL,
        repetition_index INTEGER NOT NULL,
        execution_status TEXT NOT NULL,
        disposition TEXT,
        relevance_score REAL,
        stage_latencies_json TEXT,
        token_counts_json TEXT,
        attempt_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (pair_id) REFERENCES eval_pairs(pair_id)
    );

    CREATE INDEX IF NOT EXISTS idx_eval_arm_attempts_pair
    ON eval_arm_attempts(pair_id);

    CREATE TABLE IF NOT EXISTS eval_corrections (
        correction_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        arm_id TEXT,
        reviewer_id TEXT NOT NULL,
        target_type TEXT NOT NULL,
        old_value_json TEXT NOT NULL,
        new_value_json TEXT NOT NULL,
        reason TEXT NOT NULL,
        active_review_seconds REAL NOT NULL,
        adjudication_status TEXT NOT NULL,
        correction_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_eval_corrections_case
    ON eval_corrections(case_id);

    CREATE TABLE IF NOT EXISTS eval_samples (
        sample_id TEXT PRIMARY KEY,
        population_cohort_id TEXT NOT NULL,
        population_size INTEGER NOT NULL,
        sample_size INTEGER NOT NULL,
        sampling_seed INTEGER NOT NULL,
        frame_hash TEXT NOT NULL,
        sample_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS eval_reports (
        report_id TEXT PRIMARY KEY,
        experiment_id TEXT NOT NULL,
        generated_at TEXT NOT NULL,
        total_cases INTEGER NOT NULL,
        completed_pairs INTEGER NOT NULL,
        report_json TEXT NOT NULL,
        FOREIGN KEY (experiment_id) REFERENCES eval_experiments(experiment_id)
    );

    CREATE INDEX IF NOT EXISTS idx_eval_reports_exp
    ON eval_reports(experiment_id);
    """)


EVAL_MIGRATIONS: list[tuple[int, str, MigrationFn]] = [
    (1, "001_initial_evaluation_schema", _migration_001_initial_evaluation_schema),
]


def initialize_evaluation_migrations(conn: sqlite3.Connection) -> int:
    """Apply all unapplied migrations to the evaluation database."""
    conn.execute("""
    CREATE TABLE IF NOT EXISTS eval_schema_migrations (
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        applied_at TEXT NOT NULL
    );
    """)

    cursor = conn.execute("SELECT version FROM eval_schema_migrations ORDER BY version ASC")
    applied = {row[0] for row in cursor.fetchall()}

    newly_applied = 0
    for version, name, fn in EVAL_MIGRATIONS:
        if version not in applied:
            fn(conn)
            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO eval_schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, now_iso),
            )
            newly_applied += 1

    conn.commit()
    return newly_applied

