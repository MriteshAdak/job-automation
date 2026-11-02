"""Schema migrations runner and versioned DDL definitions.

Supports forward sequential migrations, tracks applied versions in `schema_migrations`,
validates checksums, guarantees transaction rollback on migration failure, and
preserves existing data across schema upgrades (blueprint §6/DATA-01).
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from job_automation.storage.exceptions import MigrationError


MIGRATION_001_INITIAL = """
-- 001_initial.sql: Core schema baseline for job automation storage

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    start_time TEXT NOT NULL,
    end_time TEXT,
    status TEXT NOT NULL,
    source_counts_json TEXT NOT NULL DEFAULT '{}',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    summary_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_stages (
    stage_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_json TEXT,
    checkpoint_json TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS raw_postings (
    provider TEXT NOT NULL,
    board_id TEXT NOT NULL,
    source_posting_id TEXT NOT NULL,
    raw_payload_ref TEXT NOT NULL,
    raw_content_hash TEXT NOT NULL,
    fetch_time TEXT NOT NULL,
    headers_json TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (provider, board_id, source_posting_id)
);

CREATE TABLE IF NOT EXISTS fetch_manifests (
    manifest_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    source_key TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    outcome TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS canonical_jobs (
    canonical_job_id TEXT PRIMARY KEY,
    canonical_company_id TEXT,
    company_name TEXT NOT NULL,
    availability TEXT NOT NULL,
    current_revision_id TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    duplicate_proposal_reason TEXT,
    job_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posting_revisions (
    revision_id TEXT PRIMARY KEY,
    canonical_job_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    board_id TEXT NOT NULL,
    source_posting_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    title TEXT NOT NULL,
    availability TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    revision_json TEXT NOT NULL,
    FOREIGN KEY (canonical_job_id) REFERENCES canonical_jobs(canonical_job_id) ON DELETE CASCADE,
    UNIQUE (canonical_job_id, content_hash)
);

CREATE TABLE IF NOT EXISTS normalized_postings (
    provider TEXT NOT NULL,
    board_id TEXT NOT NULL,
    source_posting_id TEXT NOT NULL,
    raw_reference TEXT NOT NULL,
    raw_content_hash TEXT NOT NULL,
    title TEXT NOT NULL,
    company_name_hint TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    posting_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (provider, board_id, source_posting_id)
);

CREATE TABLE IF NOT EXISTS assessments (
    assessment_id TEXT PRIMARY KEY,
    canonical_job_id TEXT NOT NULL,
    posting_revision TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    assessment_method TEXT NOT NULL,
    relevance_decision TEXT NOT NULL,
    relevance_score REAL,
    final_disposition TEXT NOT NULL,
    summary_reason TEXT NOT NULL,
    assessment_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (canonical_job_id) REFERENCES canonical_jobs(canonical_job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sync_operations (
    operation_id TEXT PRIMARY KEY,
    canonical_job_id TEXT NOT NULL,
    payload_version TEXT NOT NULL,
    payload_fingerprint TEXT NOT NULL,
    state TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    remote_record_id TEXT,
    remote_acknowledged_at TEXT,
    error_json TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (canonical_job_id) REFERENCES canonical_jobs(canonical_job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS generation_requests (
    request_id TEXT PRIMARY KEY,
    salesforce_request_id TEXT,
    client_request_key TEXT,
    canonical_job_id TEXT NOT NULL,
    document_type TEXT NOT NULL,
    target_language TEXT NOT NULL DEFAULT 'de',
    template_id TEXT NOT NULL,
    context_strategy TEXT NOT NULL DEFAULT 'json',
    allow_unavailable_job INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    claimed_at TEXT,
    completed_at TEXT,
    frozen_inputs_json TEXT,
    predecessor_request_id TEXT,
    result_artifact_ref TEXT,
    error_json TEXT,
    request_json TEXT NOT NULL,
    FOREIGN KEY (canonical_job_id) REFERENCES canonical_jobs(canonical_job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    artifact_version INTEGER NOT NULL DEFAULT 1,
    format TEXT NOT NULL,
    local_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    remote_file_id TEXT,
    delivery_status TEXT NOT NULL,
    approval_status TEXT NOT NULL,
    reconciliation_marker TEXT,
    artifact_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (request_id) REFERENCES generation_requests(request_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_run_stages_run ON run_stages(run_id, status);
CREATE INDEX IF NOT EXISTS idx_sync_ops_state ON sync_operations(state);
CREATE INDEX IF NOT EXISTS idx_sync_ops_canonical ON sync_operations(canonical_job_id);
CREATE INDEX IF NOT EXISTS idx_gen_req_state ON generation_requests(state);
CREATE INDEX IF NOT EXISTS idx_gen_req_canonical ON generation_requests(canonical_job_id);
CREATE INDEX IF NOT EXISTS idx_canonical_jobs_avail ON canonical_jobs(availability);
CREATE INDEX IF NOT EXISTS idx_posting_revisions_hash ON posting_revisions(content_hash);
CREATE INDEX IF NOT EXISTS idx_assessments_canonical ON assessments(canonical_job_id);
"""


MIGRATION_002_CHECKPOINTS_AND_AUDIT = """
-- 002_stage_checkpoints_and_audit.sql: Add dedicated checkpoints table and audit columns

CREATE TABLE IF NOT EXISTS pipeline_checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    checkpoint_key TEXT NOT NULL,
    checkpoint_data_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_run_stage ON pipeline_checkpoints(run_id, stage_name);

ALTER TABLE runs ADD COLUMN notes TEXT;
ALTER TABLE sync_operations ADD COLUMN reconciliation_marker TEXT;
"""


MIGRATION_003_PROFILE_EVIDENCE_AND_SNAPSHOTS = """
-- 003_profile_evidence_and_snapshots.sql: Schema for candidate profiles, immutable snapshots, and provenance

CREATE TABLE IF NOT EXISTS profiles (
    candidate_id TEXT NOT NULL,
    profile_version TEXT PRIMARY KEY,
    version_sequence INTEGER NOT NULL,
    predecessor_version TEXT,
    is_current INTEGER NOT NULL DEFAULT 0,
    approved_by TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    notes TEXT,
    content_hash TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (candidate_id, version_sequence)
);

CREATE TABLE IF NOT EXISTS profile_current (
    candidate_id TEXT PRIMARY KEY,
    current_version TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (current_version) REFERENCES profiles(profile_version) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS profile_facts (
    profile_version TEXT NOT NULL,
    fact_id TEXT NOT NULL,
    parent_id TEXT,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    allowed_uses_json TEXT NOT NULL,
    provenance TEXT NOT NULL,
    fact_json TEXT NOT NULL,
    PRIMARY KEY (profile_version, fact_id),
    FOREIGN KEY (profile_version) REFERENCES profiles(profile_version) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS profile_provenance (
    provenance_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    locator TEXT NOT NULL,
    content_hash TEXT,
    file_path TEXT,
    captured_at TEXT NOT NULL,
    notes TEXT,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS profile_drafts (
    draft_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    base_profile_version TEXT,
    content_digest TEXT NOT NULL,
    draft_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (base_profile_version) REFERENCES profiles(profile_version) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_profiles_candidate ON profiles(candidate_id);
CREATE INDEX IF NOT EXISTS idx_profile_facts_fact ON profile_facts(fact_id);
CREATE INDEX IF NOT EXISTS idx_profile_drafts_candidate ON profile_drafts(candidate_id);
"""


MIGRATION_004_IDENTITY_TRACKING_AND_LINEAGE = """
-- 004_identity_tracking_and_lineage.sql: Schema for company entities, source identities, observations, review cases, and merge lineage

CREATE TABLE IF NOT EXISTS companies (
    company_id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS company_aliases (
    alias_id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    namespace TEXT NOT NULL,
    alias_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE,
    UNIQUE (namespace, alias_key)
);

CREATE TABLE IF NOT EXISTS source_identities (
    provider TEXT NOT NULL,
    board_id TEXT NOT NULL,
    source_posting_id TEXT NOT NULL,
    canonical_job_id TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (provider, board_id, source_posting_id),
    FOREIGN KEY (canonical_job_id) REFERENCES canonical_jobs(canonical_job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS posting_observations (
    observation_id TEXT PRIMARY KEY,
    canonical_job_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    board_id TEXT NOT NULL,
    source_posting_id TEXT NOT NULL,
    raw_reference TEXT NOT NULL,
    raw_content_hash TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (canonical_job_id) REFERENCES canonical_jobs(canonical_job_id) ON DELETE CASCADE,
    FOREIGN KEY (revision_id) REFERENCES posting_revisions(revision_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS identity_review_cases (
    case_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    candidate_job_ids_json TEXT NOT NULL,
    source_key_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    decision_actor TEXT,
    decision_reason TEXT,
    decided_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS identity_merge_events (
    operation_id TEXT PRIMARY KEY,
    operation_type TEXT NOT NULL,
    surviving_canonical_id TEXT NOT NULL,
    merged_canonical_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    details_json TEXT NOT NULL,
    reversed_by_operation_id TEXT,
    created_at TEXT NOT NULL,
    reversed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_identities_canonical ON source_identities(canonical_job_id);
CREATE INDEX IF NOT EXISTS idx_posting_observations_job ON posting_observations(canonical_job_id);
CREATE INDEX IF NOT EXISTS idx_posting_observations_rev ON posting_observations(revision_id);
CREATE INDEX IF NOT EXISTS idx_identity_review_status ON identity_review_cases(status);
CREATE INDEX IF NOT EXISTS idx_company_aliases_lookup ON company_aliases(namespace, alias_key);
"""


MIGRATION_005_AVAILABILITY_TRACKING = """
-- 005_availability_tracking.sql: Schema for source posting availability, decisions, and inventory consumption

CREATE TABLE IF NOT EXISTS source_posting_availability (
    provider TEXT NOT NULL,
    board_id TEXT NOT NULL,
    source_posting_id TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    canonical_job_id TEXT,
    availability TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    missing_since TEXT,
    miss_count INTEGER NOT NULL DEFAULT 0,
    policy_fingerprint TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (provider, board_id, source_posting_id, scope_id)
);

CREATE TABLE IF NOT EXISTS availability_decisions (
    decision_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    board_id TEXT NOT NULL,
    source_posting_id TEXT NOT NULL,
    canonical_job_id TEXT,
    scope_id TEXT NOT NULL,
    manifest_id TEXT,
    run_id TEXT,
    from_availability TEXT NOT NULL,
    to_availability TEXT NOT NULL,
    reason TEXT NOT NULL,
    miss_count INTEGER NOT NULL,
    missing_since TEXT,
    event_time TEXT NOT NULL,
    policy_fingerprint TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS consumed_inventories (
    consumption_id TEXT PRIMARY KEY,
    manifest_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    source_key TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    inventory_semantics TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    has_evaluated_negative INTEGER NOT NULL DEFAULT 0,
    processed_at TEXT NOT NULL,
    positive_count INTEGER NOT NULL,
    miss_count INTEGER NOT NULL,
    change_count INTEGER NOT NULL,
    UNIQUE (run_id, source_key, scope_id)
);

CREATE INDEX IF NOT EXISTS idx_source_avail_canonical ON source_posting_availability(canonical_job_id);
CREATE INDEX IF NOT EXISTS idx_source_avail_scope ON source_posting_availability(scope_id);
CREATE INDEX IF NOT EXISTS idx_avail_decisions_source ON availability_decisions(provider, board_id, source_posting_id);
CREATE INDEX IF NOT EXISTS idx_avail_decisions_canonical ON availability_decisions(canonical_job_id);
CREATE INDEX IF NOT EXISTS idx_avail_decisions_manifest ON availability_decisions(manifest_id);
CREATE INDEX IF NOT EXISTS idx_consumed_inventories_manifest ON consumed_inventories(manifest_id);
"""

MIGRATION_006_CONTEXT_INDEXES = """
-- 006_context_indexes.sql: Vector and keyword index generations, activations, build records, and pins

CREATE TABLE IF NOT EXISTS context_index_generations (
    generation_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    purpose TEXT NOT NULL,
    snapshot_fingerprint TEXT NOT NULL,
    chunk_manifest_hash TEXT NOT NULL,
    embedding_space_fingerprint TEXT NOT NULL,
    settings_fingerprint TEXT NOT NULL,
    logical_build_fingerprint TEXT NOT NULL,
    artifact_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    dimension INTEGER NOT NULL,
    generation_dir TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    finalized_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_context_index_candidate_purpose
ON context_index_generations(candidate_id, purpose, status);

CREATE TABLE IF NOT EXISTS context_index_activations (
    candidate_id TEXT NOT NULL,
    purpose TEXT NOT NULL,
    active_generation_id TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    activation_token TEXT NOT NULL,
    activated_at TEXT NOT NULL,
    PRIMARY KEY (candidate_id, purpose),
    FOREIGN KEY (active_generation_id) REFERENCES context_index_generations(generation_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS context_index_build_records (
    build_id TEXT PRIMARY KEY,
    generation_id TEXT,
    candidate_id TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    purpose TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    duration_ms REAL NOT NULL,
    chunk_count INTEGER NOT NULL,
    call_count INTEGER NOT NULL,
    call_ids_json TEXT NOT NULL DEFAULT '[]',
    error_json TEXT,
    record_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_context_index_builds_candidate
ON context_index_build_records(candidate_id, purpose, started_at);

CREATE TABLE IF NOT EXISTS context_index_pins (
    pin_id TEXT PRIMARY KEY,
    generation_id TEXT NOT NULL,
    pinned_for TEXT NOT NULL,
    pinned_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    released_at TEXT,
    FOREIGN KEY (generation_id) REFERENCES context_index_generations(generation_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_context_index_pins_gen
ON context_index_pins(generation_id, released_at);
"""

MIGRATION_007_SYNC_LIFECYCLE_AND_ORDERING = """
-- 007_sync_lifecycle_and_ordering.sql: Schema for SYNC-01 plans, steps, ordering lanes, mappings, barriers, and candidate snapshots

CREATE TABLE IF NOT EXISTS sync_plans (
    plan_id TEXT PRIMARY KEY,
    canonical_job_id TEXT NOT NULL,
    assessment_id TEXT NOT NULL,
    mapping_version TEXT NOT NULL,
    mapping_hash TEXT NOT NULL,
    plan_fingerprint TEXT NOT NULL,
    selection_token TEXT NOT NULL,
    run_id TEXT,
    publication_decision TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (canonical_job_id) REFERENCES canonical_jobs(canonical_job_id) ON DELETE CASCADE,
    FOREIGN KEY (assessment_id) REFERENCES assessments(assessment_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sync_write_steps (
    step_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    operation_id TEXT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,
    target_object TEXT NOT NULL,
    external_id_field TEXT NOT NULL,
    external_id_value TEXT NOT NULL,
    relationship_field TEXT,
    depends_on_step_id TEXT,
    frozen_payload_json TEXT NOT NULL,
    step_fingerprint TEXT NOT NULL,
    state TEXT NOT NULL,
    may_have_been_sent INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    reconciliation_marker TEXT NOT NULL,
    remote_record_id TEXT,
    acknowledged_at TEXT,
    error_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (plan_id) REFERENCES sync_plans(plan_id) ON DELETE CASCADE,
    FOREIGN KEY (operation_id) REFERENCES sync_operations(operation_id) ON DELETE SET NULL,
    FOREIGN KEY (depends_on_step_id) REFERENCES sync_write_steps(step_id) ON DELETE SET NULL,
    UNIQUE (entity_type, entity_id, sequence_number)
);

CREATE TABLE IF NOT EXISTS sync_entity_heads (
    org_id TEXT NOT NULL,
    target_object TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    head_sequence INTEGER NOT NULL DEFAULT 0,
    confirmed_sequence INTEGER NOT NULL DEFAULT 0,
    locked_by TEXT,
    locked_until TEXT,
    has_barrier INTEGER NOT NULL DEFAULT 0,
    barrier_reason TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (org_id, target_object, entity_id)
);

CREATE TABLE IF NOT EXISTS sync_remote_mappings (
    org_id TEXT NOT NULL,
    target_object TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    external_id TEXT NOT NULL,
    salesforce_id TEXT NOT NULL,
    confirmed_sequence INTEGER NOT NULL,
    reconciliation_marker TEXT,
    acknowledged_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (org_id, target_object, entity_id),
    UNIQUE (org_id, target_object, external_id)
);

CREATE TABLE IF NOT EXISTS sync_selection_heads (
    canonical_job_id TEXT PRIMARY KEY,
    active_generation_token TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (canonical_job_id) REFERENCES canonical_jobs(canonical_job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS candidate_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    canonical_job_id TEXT NOT NULL,
    remote_record_id TEXT NOT NULL,
    mapping_version TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    candidate_fields_json TEXT NOT NULL,
    source_modification_token TEXT,
    observed_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (canonical_job_id) REFERENCES canonical_jobs(canonical_job_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS candidate_backup_checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    last_processed_key TEXT,
    is_complete INTEGER NOT NULL DEFAULT 0,
    records_processed INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_sync_plans_job ON sync_plans(canonical_job_id);
CREATE INDEX IF NOT EXISTS idx_sync_steps_plan ON sync_write_steps(plan_id);
CREATE INDEX IF NOT EXISTS idx_sync_steps_due ON sync_write_steps(state, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_sync_steps_entity ON sync_write_steps(entity_type, entity_id, sequence_number);
CREATE INDEX IF NOT EXISTS idx_candidate_snapshots_job ON candidate_snapshots(canonical_job_id, observed_at);
"""


MIGRATION_008_PIPELINE_WORK_AND_RUN_ATTEMPTS = """
-- 008_pipeline_work_and_run_attempts.sql: Schema for RUN-01 requests, attempts, work receipts, bindings, and selections

CREATE TABLE IF NOT EXISTS run_requests (
    run_id TEXT PRIMARY KEY,
    request_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_attempts (
    attempt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    attempt_sequence INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    exit_code INTEGER,
    error_json TEXT,
    UNIQUE (run_id, attempt_sequence)
);

CREATE TABLE IF NOT EXISTS stage_work_records (
    work_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    work_key TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    output_id TEXT,
    state TEXT NOT NULL,
    checkpoint_json TEXT,
    error_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (stage_name, work_key, input_fingerprint)
);

CREATE TABLE IF NOT EXISTS posting_bindings (
    binding_id TEXT PRIMARY KEY,
    canonical_job_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    normalized_content_hash TEXT NOT NULL,
    raw_reference TEXT NOT NULL,
    raw_content_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    board_id TEXT NOT NULL,
    source_posting_id TEXT NOT NULL,
    c06_json TEXT NOT NULL,
    mapper_version TEXT NOT NULL,
    normalizer_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (canonical_job_id, revision_id)
);

CREATE TABLE IF NOT EXISTS assessment_selections (
    selection_id TEXT PRIMARY KEY,
    canonical_job_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    purpose TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    assessment_id TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    generation_token TEXT NOT NULL,
    is_selected_final INTEGER NOT NULL,
    disposition TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (canonical_job_id, purpose, generation_token)
);

CREATE TABLE IF NOT EXISTS quarantine_records (
    quarantine_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    board_id TEXT NOT NULL,
    source_posting_id TEXT NOT NULL,
    raw_reference TEXT NOT NULL,
    record_index INTEGER,
    issues_json TEXT NOT NULL,
    draft_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_reports (
    report_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    report_version TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_run_attempts_run ON run_attempts(run_id);
CREATE INDEX IF NOT EXISTS idx_stage_work_run ON stage_work_records(run_id, stage_name);
CREATE INDEX IF NOT EXISTS idx_posting_bindings_canonical ON posting_bindings(canonical_job_id);
CREATE INDEX IF NOT EXISTS idx_posting_bindings_source ON posting_bindings(provider, board_id, source_posting_id);
CREATE INDEX IF NOT EXISTS idx_assessment_selections_canonical ON assessment_selections(canonical_job_id, is_selected_final);
CREATE INDEX IF NOT EXISTS idx_quarantine_run ON quarantine_records(run_id);
CREATE INDEX IF NOT EXISTS idx_run_reports_run ON run_reports(run_id);
"""

MIGRATION_009_OPERATIONS_JOURNAL_AND_PLANS = """
-- 009_operations_journal_and_plans.sql: Tables for operations cleanup plans, execution journals, reports, and backups

CREATE TABLE IF NOT EXISTS ops_cleanup_plans (
    plan_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    store_fingerprint TEXT NOT NULL,
    policy_fingerprint TEXT NOT NULL,
    plan_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    plan_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ops_cleanup_journals (
    journal_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    step_number INTEGER NOT NULL,
    item_path TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    reclaimed_bytes INTEGER NOT NULL DEFAULT 0,
    details_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (plan_id) REFERENCES ops_cleanup_plans(plan_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ops_maintenance_reports (
    report_id TEXT PRIMARY KEY,
    operation_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    status TEXT NOT NULL,
    integrity_verified INTEGER NOT NULL DEFAULT 0,
    restore_tested INTEGER NOT NULL DEFAULT 0,
    remote_coverage_status TEXT NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ops_backups (
    backup_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    backup_path TEXT NOT NULL,
    format_version TEXT NOT NULL,
    app_version TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    completeness_status TEXT NOT NULL,
    is_pinned INTEGER NOT NULL DEFAULT 0,
    manifest_json TEXT NOT NULL,
    status TEXT NOT NULL,
    verified_at TEXT,
    restore_tested_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_ops_cleanup_journals_plan ON ops_cleanup_journals(plan_id);
CREATE INDEX IF NOT EXISTS idx_ops_maintenance_reports_type ON ops_maintenance_reports(operation_type);
CREATE INDEX IF NOT EXISTS idx_ops_backups_status ON ops_backups(status);
"""


MIGRATION_010_GENERATION_WORKFLOW_AND_CHECKPOINTS = """
-- 010_generation_workflow_and_checkpoints.sql: Durable companion records for generation workflow (GEN-01)

CREATE TABLE IF NOT EXISTS generation_request_observations (
    observation_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    salesforce_request_id TEXT NOT NULL,
    canonical_salesforce_id TEXT NOT NULL,
    client_request_key TEXT,
    local_request_id TEXT,
    canonical_job_id TEXT,
    remote_state TEXT NOT NULL,
    observed_options_digest TEXT,
    observed_at TEXT NOT NULL,
    remote_updated_at TEXT,
    issue_category TEXT,
    issue_message TEXT,
    raw_record_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gen_obs_remote ON generation_request_observations(org_id, canonical_salesforce_id);
CREATE INDEX IF NOT EXISTS idx_gen_obs_local ON generation_request_observations(local_request_id);

CREATE TABLE IF NOT EXISTS generation_freeze_associations (
    request_id TEXT PRIMARY KEY,
    manifest_id TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    canonical_job_id TEXT NOT NULL,
    posting_revision_id TEXT NOT NULL,
    posting_revision_hash TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    template_id TEXT NOT NULL,
    template_version TEXT NOT NULL,
    context_strategy TEXT NOT NULL,
    target_language TEXT NOT NULL,
    options_digest TEXT NOT NULL,
    availability_status TEXT NOT NULL,
    allow_unavailable_job INTEGER NOT NULL DEFAULT 0,
    frozen_at TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    FOREIGN KEY (request_id) REFERENCES generation_requests(request_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS generation_request_checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    stage_operation_id TEXT NOT NULL,
    checkpoint_revision INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    output_ref TEXT,
    output_hash TEXT,
    error_json TEXT,
    checkpoint_data_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (request_id) REFERENCES generation_requests(request_id) ON DELETE CASCADE,
    UNIQUE (request_id, stage_name)
);

CREATE INDEX IF NOT EXISTS idx_gen_chk_req_status ON generation_request_checkpoints(request_id, status);

CREATE TABLE IF NOT EXISTS generation_request_attempts (
    attempt_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    stage_operation_id TEXT NOT NULL,
    attempt_sequence INTEGER NOT NULL,
    worker_attempt_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_json TEXT,
    FOREIGN KEY (request_id) REFERENCES generation_requests(request_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_gen_att_req_stage ON generation_request_attempts(request_id, stage_name);

CREATE TABLE IF NOT EXISTS generation_projection_intents (
    intent_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    projection_revision INTEGER NOT NULL,
    operation_marker TEXT NOT NULL,
    desired_remote_state TEXT NOT NULL,
    expected_remote_state TEXT,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    acknowledged_at TEXT,
    uncertain_at TEXT,
    last_error_json TEXT,
    FOREIGN KEY (request_id) REFERENCES generation_requests(request_id) ON DELETE CASCADE,
    UNIQUE (request_id, projection_revision)
);

CREATE INDEX IF NOT EXISTS idx_gen_proj_req_status ON generation_projection_intents(request_id, status);
CREATE INDEX IF NOT EXISTS idx_gen_proj_status ON generation_projection_intents(status);

CREATE TABLE IF NOT EXISTS generation_artifact_deliveries (
    delivery_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    artifact_format TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    artifact_hash TEXT NOT NULL,
    remote_file_id TEXT,
    delivery_status TEXT NOT NULL,
    delivered_at TEXT,
    receipt_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (request_id) REFERENCES generation_requests(request_id) ON DELETE CASCADE,
    UNIQUE (request_id, artifact_format)
);

CREATE INDEX IF NOT EXISTS idx_gen_art_req_fmt ON generation_artifact_deliveries(request_id, artifact_format);

CREATE INDEX IF NOT EXISTS idx_gen_req_sf_id ON generation_requests(salesforce_request_id);
CREATE INDEX IF NOT EXISTS idx_gen_req_client_key ON generation_requests(client_request_key);

CREATE TRIGGER IF NOT EXISTS trg_protect_claimed_generation_requests
BEFORE DELETE ON canonical_jobs
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM generation_requests
    WHERE canonical_job_id = OLD.canonical_job_id
      AND state IN ('running', 'upload_pending', 'ready_for_review')
)
BEGIN
    SELECT RAISE(ABORT, 'Cannot delete canonical job referenced by claimed generation request');
END;
"""


MIGRATION_011_FROZEN_INPUTS_AND_PREFLIGHT = """
-- 011_frozen_inputs_and_preflight.sql: Immutable input seals, preflight receipts, and context receipts (GEN-02)

CREATE TABLE IF NOT EXISTS generation_preflight_receipts (
    receipt_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    freeze_op_id TEXT NOT NULL,
    accepted_options_digest TEXT NOT NULL,
    result TEXT NOT NULL,
    seal_id TEXT,
    seal_hash TEXT,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    error_json TEXT,
    reason_code TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gen_preflight_req ON generation_preflight_receipts(request_id);

CREATE TABLE IF NOT EXISTS generation_frozen_seals (
    seal_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE,
    manifest_id TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    options_digest TEXT NOT NULL,
    canonical_job_id TEXT NOT NULL,
    posting_revision_id TEXT NOT NULL,
    posting_revision_hash TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    template_id TEXT NOT NULL,
    template_version TEXT NOT NULL,
    context_strategy TEXT NOT NULL,
    target_language TEXT NOT NULL,
    availability_status TEXT NOT NULL,
    allow_unavailable_job INTEGER NOT NULL DEFAULT 0,
    frozen_at TEXT NOT NULL,
    seal_hash TEXT NOT NULL,
    seal_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (request_id) REFERENCES generation_requests(request_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_gen_frozen_seals_manifest ON generation_frozen_seals(manifest_id);
CREATE INDEX IF NOT EXISTS idx_gen_frozen_seals_req ON generation_frozen_seals(request_id);

CREATE TABLE IF NOT EXISTS generation_frozen_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    seal_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    snapshot_digest TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (seal_id) REFERENCES generation_frozen_seals(seal_id) ON DELETE RESTRICT,
    UNIQUE (seal_id, kind)
);

CREATE INDEX IF NOT EXISTS idx_gen_frozen_snap_seal ON generation_frozen_snapshots(seal_id);

CREATE TABLE IF NOT EXISTS generation_context_receipts (
    receipt_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    manifest_id TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    recipe_hash TEXT NOT NULL,
    context_op_id TEXT NOT NULL,
    result_hash TEXT NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (request_id) REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    UNIQUE (request_id, result_hash)
);

CREATE INDEX IF NOT EXISTS idx_gen_ctx_rec_req ON generation_context_receipts(request_id);

CREATE TRIGGER IF NOT EXISTS trg_protect_sealed_generation_jobs
BEFORE DELETE ON canonical_jobs
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM generation_frozen_seals
    WHERE canonical_job_id = OLD.canonical_job_id
)
BEGIN
    SELECT RAISE(ABORT, 'Cannot delete canonical job referenced by sealed generation input');
END;
"""


MIGRATION_012_DRAFT_CONTENT = """
CREATE TABLE draft_content_attempts (
    attempt_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    logical_key TEXT NOT NULL,
    binding_hash TEXT NOT NULL,
    seal_id TEXT NOT NULL REFERENCES generation_frozen_seals(seal_id) ON DELETE RESTRICT,
    context_receipt_id TEXT NOT NULL REFERENCES generation_context_receipts(receipt_id) ON DELETE RESTRICT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    call_json TEXT,
    call_id TEXT NOT NULL UNIQUE,
    receipt_json TEXT,
    receipt_hash TEXT
);
CREATE TABLE draft_model_audits (
    call_id TEXT PRIMARY KEY REFERENCES draft_content_attempts(call_id) ON DELETE RESTRICT,
    audit_json TEXT NOT NULL,
    audit_hash TEXT NOT NULL
);
CREATE TABLE draft_content_results (
    request_id TEXT PRIMARY KEY REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    logical_key TEXT NOT NULL UNIQUE,
    receipt_id TEXT NOT NULL UNIQUE REFERENCES draft_content_attempts(attempt_id) ON DELETE RESTRICT
);
"""


MIGRATION_013_DOCUMENT_VALIDATION = """
CREATE TABLE document_validation_attempts (
    attempt_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    logical_key TEXT NOT NULL,
    binding_hash TEXT NOT NULL,
    draft_receipt_id TEXT NOT NULL REFERENCES draft_content_attempts(attempt_id) ON DELETE RESTRICT,
    draft_hash TEXT NOT NULL,
    rule_set_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    report_json TEXT,
    report_hash TEXT,
    fatal_count INTEGER,
    warning_count INTEGER,
    render_decision TEXT
);
CREATE TABLE document_validation_results (
    request_id TEXT PRIMARY KEY REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    logical_key TEXT NOT NULL UNIQUE,
    attempt_id TEXT NOT NULL UNIQUE REFERENCES document_validation_attempts(attempt_id) ON DELETE RESTRICT,
    report_hash TEXT NOT NULL,
    render_decision TEXT NOT NULL
);
"""


MIGRATION_014_RENDER_ARTIFACTS = """
-- 014_render_artifacts.sql: Render intents, execution attempts, immutable receipts, and artifact sets (GEN-05)

CREATE TABLE IF NOT EXISTS render_intents (
    intent_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    logical_key TEXT NOT NULL UNIQUE,
    spec_hash TEXT NOT NULL,
    artifact_version INTEGER NOT NULL DEFAULT 1,
    target_formats_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_render_int_req ON render_intents(request_id);

CREATE TABLE IF NOT EXISTS render_attempts (
    attempt_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL REFERENCES render_intents(intent_id) ON DELETE RESTRICT,
    request_id TEXT NOT NULL REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    attempt_number INTEGER NOT NULL,
    format TEXT NOT NULL,
    staging_dir TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    exit_code INTEGER,
    duration_ms INTEGER,
    error_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_render_att_int ON render_attempts(intent_id);
CREATE INDEX IF NOT EXISTS idx_render_att_req ON render_attempts(request_id);

CREATE TABLE IF NOT EXISTS rendered_artifact_receipts (
    receipt_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    artifact_id TEXT NOT NULL UNIQUE,
    artifact_set_id TEXT NOT NULL,
    format TEXT NOT NULL,
    version INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    local_path TEXT NOT NULL,
    relative_managed_path TEXT NOT NULL,
    spec_hash TEXT NOT NULL,
    draft_hash TEXT NOT NULL,
    report_hash TEXT NOT NULL,
    layout_digest TEXT NOT NULL,
    docx_artifact_id TEXT,
    docx_content_hash TEXT,
    output_checks_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    receipt_hash TEXT NOT NULL,
    UNIQUE(request_id, version, format)
);

CREATE INDEX IF NOT EXISTS idx_rend_rcpt_req ON rendered_artifact_receipts(request_id);

CREATE TABLE IF NOT EXISTS artifact_sets (
    set_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    set_version INTEGER NOT NULL,
    required_formats_json TEXT NOT NULL,
    is_complete INTEGER NOT NULL DEFAULT 0,
    report_id TEXT NOT NULL,
    report_hash TEXT NOT NULL,
    draft_hash TEXT NOT NULL,
    set_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(request_id, set_version)
);

CREATE INDEX IF NOT EXISTS idx_art_set_req ON artifact_sets(request_id);
"""

MIGRATION_015_ARTIFACT_DELIVERIES = """
-- 015_artifact_deliveries.sql: Durable delivery intents, attempts, remote mappings, access proofs, and delivery set receipts (GEN-06-S02)

CREATE TABLE IF NOT EXISTS delivery_intents (
    intent_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL,
    salesforce_request_id TEXT NOT NULL,
    canonical_salesforce_id TEXT,
    request_id TEXT NOT NULL REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    artifact_set_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    artifact_version INTEGER NOT NULL DEFAULT 1,
    artifact_format TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    local_path TEXT NOT NULL,
    reconciliation_marker TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(org_id, request_id, artifact_id, artifact_version),
    UNIQUE(org_id, reconciliation_marker)
);

CREATE INDEX IF NOT EXISTS idx_delivery_intents_req ON delivery_intents(request_id);
CREATE INDEX IF NOT EXISTS idx_delivery_intents_marker ON delivery_intents(org_id, reconciliation_marker);

CREATE TABLE IF NOT EXISTS delivery_attempts (
    attempt_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL REFERENCES delivery_intents(intent_id) ON DELETE CASCADE,
    request_id TEXT NOT NULL REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    attempt_sequence INTEGER NOT NULL,
    operation_kind TEXT NOT NULL,
    phase TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    exit_code INTEGER,
    duration_ms INTEGER,
    error_json TEXT,
    outcome_evidence_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_delivery_attempts_intent ON delivery_attempts(intent_id);

CREATE TABLE IF NOT EXISTS remote_artifact_mappings (
    mapping_id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL REFERENCES delivery_intents(intent_id) ON DELETE CASCADE,
    request_id TEXT NOT NULL REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    artifact_id TEXT NOT NULL,
    artifact_version INTEGER NOT NULL,
    artifact_format TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    org_id TEXT NOT NULL,
    content_document_id TEXT NOT NULL,
    content_version_id TEXT NOT NULL,
    provider_version_label TEXT,
    marker TEXT NOT NULL,
    target_record_id TEXT NOT NULL,
    link_id TEXT,
    acknowledged_at TEXT NOT NULL,
    UNIQUE(org_id, request_id, artifact_id, artifact_version)
);

CREATE INDEX IF NOT EXISTS idx_remote_mappings_req ON remote_artifact_mappings(request_id);
CREATE INDEX IF NOT EXISTS idx_remote_mappings_doc ON remote_artifact_mappings(org_id, content_document_id);
CREATE INDEX IF NOT EXISTS idx_remote_mappings_ver ON remote_artifact_mappings(org_id, content_version_id);

CREATE TABLE IF NOT EXISTS accessibility_receipts (
    receipt_id TEXT PRIMARY KEY,
    mapping_id TEXT NOT NULL REFERENCES remote_artifact_mappings(mapping_id) ON DELETE CASCADE,
    request_id TEXT NOT NULL REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    artifact_id TEXT NOT NULL,
    artifact_version INTEGER NOT NULL,
    artifact_format TEXT NOT NULL,
    content_version_id TEXT NOT NULL,
    content_document_id TEXT NOT NULL,
    target_record_id TEXT NOT NULL,
    verification_method TEXT NOT NULL,
    candidate_principal TEXT,
    verified_at TEXT NOT NULL,
    receipt_hash TEXT NOT NULL,
    UNIQUE(request_id, artifact_version, artifact_format)
);

CREATE INDEX IF NOT EXISTS idx_accessibility_receipts_req ON accessibility_receipts(request_id);

CREATE TABLE IF NOT EXISTS delivery_set_receipts (
    set_receipt_id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES generation_requests(request_id) ON DELETE RESTRICT,
    set_id TEXT NOT NULL,
    set_version INTEGER NOT NULL,
    required_formats_json TEXT NOT NULL,
    is_accessible INTEGER NOT NULL DEFAULT 0,
    review_route TEXT NOT NULL,
    created_at TEXT NOT NULL,
    receipt_hash TEXT NOT NULL,
    UNIQUE(request_id, set_version)
);

CREATE INDEX IF NOT EXISTS idx_delivery_set_receipts_req ON delivery_set_receipts(request_id);
"""

MIGRATION_016_SCHEDULING_OCCURRENCES_AND_LAUNCHES = """
-- AUTO-01 Native Windows scheduling definitions, occurrences, and launch attempts
CREATE TABLE IF NOT EXISTS ops_schedule_definitions (
    deployment_id TEXT NOT NULL,
    schedule_id TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    definition_hash TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    work_kind TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Europe/Berlin',
    target_times_json TEXT NOT NULL,
    cadence_minutes INTEGER,
    activation_epoch TEXT NOT NULL,
    max_lateness_hours INTEGER NOT NULL DEFAULT 24,
    max_retries INTEGER NOT NULL DEFAULT 3,
    retry_delay_seconds INTEGER NOT NULL DEFAULT 60,
    app_config_path TEXT NOT NULL,
    data_root TEXT NOT NULL,
    run_config_path TEXT,
    assessment_mode TEXT NOT NULL DEFAULT 'rules',
    llm_strategy TEXT NOT NULL DEFAULT 'json',
    command_timeout_seconds INTEGER NOT NULL DEFAULT 3600,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (deployment_id, schedule_id, version)
);

CREATE TABLE IF NOT EXISTS ops_schedule_occurrences (
    occurrence_id TEXT PRIMARY KEY,
    deployment_id TEXT NOT NULL,
    schedule_id TEXT NOT NULL,
    definition_version INTEGER NOT NULL,
    work_kind TEXT NOT NULL,
    intended_slot TEXT NOT NULL,
    intended_utc_instant TEXT NOT NULL,
    local_offset_minutes INTEGER NOT NULL,
    fold INTEGER NOT NULL DEFAULT 0,
    outcome TEXT NOT NULL,
    admitted_run_id TEXT,
    admitted_request_id TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_eligible_at TEXT,
    terminal_at TEXT,
    details_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (deployment_id, schedule_id, definition_version, intended_slot)
);

CREATE INDEX IF NOT EXISTS idx_ops_schedule_occurrences_status
ON ops_schedule_occurrences (deployment_id, schedule_id, outcome, next_eligible_at);

CREATE TABLE IF NOT EXISTS ops_launch_attempts (
    launch_id TEXT PRIMARY KEY,
    occurrence_id TEXT,
    deployment_id TEXT NOT NULL,
    schedule_id TEXT NOT NULL,
    work_kind TEXT NOT NULL,
    task_identity TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    bootstrap_status TEXT NOT NULL,
    readiness_message TEXT,
    child_pid INTEGER,
    child_exit_code INTEGER,
    outcome TEXT NOT NULL,
    application_run_id TEXT,
    report_summary_json TEXT,
    sanitized_error TEXT,
    stdout_tail TEXT,
    stderr_tail TEXT,
    FOREIGN KEY (occurrence_id) REFERENCES ops_schedule_occurrences (occurrence_id)
);

CREATE INDEX IF NOT EXISTS idx_ops_launch_attempts_occurrence
ON ops_launch_attempts (occurrence_id);
"""

MIGRATION_017_AUTOMATIC_DRAFT_POLICY_AND_HISTORY = """
-- AUTO-02 Automatic drafting policies, decisions, intents, reservations, and request bindings
CREATE TABLE IF NOT EXISTS auto_draft_policies (
    policy_id TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    policy_content_hash TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0,
    candidate_id TEXT NOT NULL,
    salesforce_org_id TEXT NOT NULL,
    policy_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (policy_id, policy_version)
);

CREATE TABLE IF NOT EXISTS auto_draft_decisions (
    decision_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    salesforce_org_id TEXT NOT NULL,
    canonical_job_id TEXT NOT NULL,
    evaluation_run_id TEXT NOT NULL,
    evaluation_attempt_id TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    policy_content_hash TEXT NOT NULL,
    decision_input_fingerprint TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    summary_reason TEXT NOT NULL,
    relevance_score REAL,
    threshold_applied REAL,
    assessment_id TEXT,
    client_request_key TEXT,
    decision_json TEXT NOT NULL,
    evaluated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auto_draft_decisions_job
ON auto_draft_decisions (canonical_job_id, evaluated_at);

CREATE INDEX IF NOT EXISTS idx_auto_draft_decisions_outcome
ON auto_draft_decisions (outcome, evaluated_at);

CREATE TABLE IF NOT EXISTS auto_draft_intents (
    intent_id TEXT PRIMARY KEY,
    client_request_key TEXT NOT NULL UNIQUE,
    candidate_id TEXT NOT NULL,
    salesforce_org_id TEXT NOT NULL,
    canonical_job_id TEXT NOT NULL,
    document_type TEXT NOT NULL,
    material_generation_fingerprint TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    policy_content_hash TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    request_payload_digest TEXT NOT NULL,
    request_payload_json TEXT NOT NULL,
    submission_state TEXT NOT NULL,
    salesforce_request_id TEXT,
    local_request_id TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auto_draft_intents_job
ON auto_draft_intents (candidate_id, salesforce_org_id, canonical_job_id, document_type);

CREATE INDEX IF NOT EXISTS idx_auto_draft_intents_mat
ON auto_draft_intents (material_generation_fingerprint);

CREATE TABLE IF NOT EXISTS auto_draft_reservations (
    reservation_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    salesforce_org_id TEXT NOT NULL,
    canonical_job_id TEXT NOT NULL,
    evaluation_run_id TEXT NOT NULL,
    intent_id TEXT NOT NULL,
    client_request_key TEXT NOT NULL,
    document_units INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    reserved_at TEXT NOT NULL,
    released_at TEXT,
    release_reason TEXT,
    FOREIGN KEY (intent_id) REFERENCES auto_draft_intents (intent_id)
);

CREATE INDEX IF NOT EXISTS idx_auto_draft_reservations_window
ON auto_draft_reservations (candidate_id, salesforce_org_id, status, reserved_at);

CREATE TABLE IF NOT EXISTS auto_draft_request_bindings (
    binding_id TEXT PRIMARY KEY,
    local_request_id TEXT NOT NULL UNIQUE,
    intent_id TEXT NOT NULL,
    client_request_key TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    salesforce_org_id TEXT NOT NULL,
    canonical_job_id TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    policy_content_hash TEXT NOT NULL,
    expected_assessment_id TEXT NOT NULL,
    expected_assessment_fingerprint TEXT NOT NULL,
    expected_material_fingerprint TEXT NOT NULL,
    expected_posting_revision_hash TEXT NOT NULL,
    expected_profile_version TEXT NOT NULL,
    expected_profile_digest TEXT NOT NULL,
    expected_search_policy_version TEXT NOT NULL,
    expected_search_policy_hash TEXT NOT NULL,
    revalidation_receipt_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (intent_id) REFERENCES auto_draft_intents (intent_id)
);

CREATE INDEX IF NOT EXISTS idx_auto_draft_bindings_intent
ON auto_draft_request_bindings (intent_id);
"""

MIGRATION_018_RUN_SUMMARY_DELIVERIES = """
-- 018_run_summary_deliveries.sql: Per-run summary delivery receipts, outbox, and attempt history (AUTO-03)

CREATE TABLE IF NOT EXISTS run_completion_receipts (
    receipt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    attempt_sequence INTEGER NOT NULL,
    revision INTEGER NOT NULL,
    start_time TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    status TEXT NOT NULL,
    c15_summary_json TEXT NOT NULL,
    report_metadata_json TEXT NOT NULL,
    receipt_hash TEXT NOT NULL,
    is_final INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE (run_id, revision)
);

CREATE INDEX IF NOT EXISTS idx_run_completion_receipts_run_id
ON run_completion_receipts (run_id);

CREATE TABLE IF NOT EXISTS run_summary_deliveries (
    delivery_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    org_id TEXT NOT NULL,
    completion_key TEXT NOT NULL,
    revision INTEGER NOT NULL,
    state TEXT NOT NULL,
    target_object TEXT NOT NULL,
    target_external_id_field TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    first_completion_hash TEXT NOT NULL,
    dispatch_attempts INTEGER NOT NULL DEFAULT 0,
    reconcile_attempts INTEGER NOT NULL DEFAULT 0,
    retry_window_start TEXT NOT NULL,
    retry_deadline TEXT NOT NULL,
    next_due_at TEXT,
    remote_record_id TEXT,
    acknowledged_revision INTEGER,
    acknowledged_hash TEXT,
    notification_state TEXT NOT NULL DEFAULT 'none',
    notification_receipt_id TEXT,
    last_error_category TEXT,
    last_error_code TEXT,
    last_error_message TEXT,
    claim_token TEXT,
    claimed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    acknowledged_at TEXT,
    UNIQUE (org_id, run_id)
);

CREATE INDEX IF NOT EXISTS idx_run_summary_deliveries_due
ON run_summary_deliveries (state, next_due_at);

CREATE INDEX IF NOT EXISTS idx_run_summary_deliveries_run_id
ON run_summary_deliveries (run_id);

CREATE TABLE IF NOT EXISTS run_summary_delivery_attempts (
    attempt_id TEXT PRIMARY KEY,
    delivery_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    attempt_sequence INTEGER NOT NULL,
    operation_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    http_status INTEGER,
    duration_ms REAL NOT NULL DEFAULT 0.0,
    remote_outcome TEXT,
    recovery_action TEXT,
    safe_error_code TEXT,
    safe_error_message TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (delivery_id) REFERENCES run_summary_deliveries (delivery_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_run_summary_delivery_attempts_delivery
ON run_summary_delivery_attempts (delivery_id);
"""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.strip().encode("utf-8")).hexdigest()


ALL_MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, name="001_initial", sql=MIGRATION_001_INITIAL),
    Migration(
        version=2,
        name="002_stage_checkpoints_and_audit",
        sql=MIGRATION_002_CHECKPOINTS_AND_AUDIT,
    ),
    Migration(
        version=3,
        name="003_profile_evidence_and_snapshots",
        sql=MIGRATION_003_PROFILE_EVIDENCE_AND_SNAPSHOTS,
    ),
    Migration(
        version=4,
        name="004_identity_tracking_and_lineage",
        sql=MIGRATION_004_IDENTITY_TRACKING_AND_LINEAGE,
    ),
    Migration(
        version=5,
        name="005_availability_tracking",
        sql=MIGRATION_005_AVAILABILITY_TRACKING,
    ),
    Migration(
        version=6,
        name="006_context_indexes",
        sql=MIGRATION_006_CONTEXT_INDEXES,
    ),
    Migration(
        version=7,
        name="007_sync_lifecycle_and_ordering",
        sql=MIGRATION_007_SYNC_LIFECYCLE_AND_ORDERING,
    ),
    Migration(
        version=8,
        name="008_pipeline_work_and_run_attempts",
        sql=MIGRATION_008_PIPELINE_WORK_AND_RUN_ATTEMPTS,
    ),
    Migration(
        version=9,
        name="009_operations_journal_and_plans",
        sql=MIGRATION_009_OPERATIONS_JOURNAL_AND_PLANS,
    ),
    Migration(
        version=10,
        name="010_generation_workflow_and_checkpoints",
        sql=MIGRATION_010_GENERATION_WORKFLOW_AND_CHECKPOINTS,
    ),
    Migration(
        version=11,
        name="011_frozen_inputs_and_preflight",
        sql=MIGRATION_011_FROZEN_INPUTS_AND_PREFLIGHT,
    ),
    Migration(version=12, name="012_draft_content", sql=MIGRATION_012_DRAFT_CONTENT),
    Migration(version=13, name="013_document_validation", sql=MIGRATION_013_DOCUMENT_VALIDATION),
    Migration(version=14, name="014_render_artifacts", sql=MIGRATION_014_RENDER_ARTIFACTS),
    Migration(version=15, name="015_artifact_deliveries", sql=MIGRATION_015_ARTIFACT_DELIVERIES),
    Migration(
        version=16,
        name="016_scheduling_occurrences_and_launches",
        sql=MIGRATION_016_SCHEDULING_OCCURRENCES_AND_LAUNCHES,
    ),
    Migration(
        version=17,
        name="017_automatic_draft_policy_and_history",
        sql=MIGRATION_017_AUTOMATIC_DRAFT_POLICY_AND_HISTORY,
    ),
    Migration(
        version=18,
        name="018_run_summary_deliveries",
        sql=MIGRATION_018_RUN_SUMMARY_DELIVERIES,
    ),
)


def _init_migrations_table(conn: sqlite3.Connection) -> None:
    """Ensure the schema_migrations tracking table exists."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            checksum TEXT NOT NULL
        );
        """
    )
    conn.commit()


def get_current_schema_version(conn: sqlite3.Connection) -> int:
    """Return highest applied schema migration version, or 0 if uninitialized."""
    _init_migrations_table(conn)
    cursor = conn.execute("SELECT MAX(version) FROM schema_migrations")
    row = cursor.fetchone()
    if row and row[0] is not None:
        return int(row[0])
    return 0


def get_applied_migrations(conn: sqlite3.Connection) -> dict[int, dict]:
    """Return dictionary of applied migration metadata indexed by version."""
    _init_migrations_table(conn)
    cursor = conn.execute(
        "SELECT version, name, applied_at, checksum FROM schema_migrations ORDER BY version ASC"
    )
    return {
        row["version"]: {
            "version": row["version"],
            "name": row["name"],
            "applied_at": row["applied_at"],
            "checksum": row["checksum"],
        }
        for row in cursor.fetchall()
    }


def _split_sql_statements(sql: str) -> list[str]:
    """Split SQL script into complete statements, respecting inner blocks and triggers."""
    statements: list[str] = []
    buffer = ""
    for part in sql.split(";"):
        if not part.strip():
            continue
        buffer = (buffer + ";" + part) if buffer else part
        if sqlite3.complete_statement(buffer + ";"):
            statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        statements.append(buffer.strip())
    return statements


def apply_migrations(
    conn: sqlite3.Connection,
    target_version: int | None = None,
    migrations: Sequence[Migration] = ALL_MIGRATIONS,
) -> list[int]:
    """Apply unapplied migrations sequentially up to target_version (or latest).

    Guarantees:
    - Verifies checksums of already applied migrations.
    - Applies each new migration within an atomic transaction.
    - Records version and timestamp in `schema_migrations`.
    - Preserves existing data across migrations.
    - Rolls back on error and raises MigrationError.
    """
    _init_migrations_table(conn)
    applied = get_applied_migrations(conn)

    # Verify checksums of existing migrations
    for m in migrations:
        if m.version in applied:
            recorded = applied[m.version]
            if recorded["checksum"] != m.checksum:
                raise MigrationError(
                    f"Migration {m.version} ({m.name}) checksum mismatch: "
                    f"expected {recorded['checksum']}, got {m.checksum}"
                )

    newly_applied: list[int] = []

    for m in migrations:
        if target_version is not None and m.version > target_version:
            break

        if m.version in applied:
            continue

        try:
            conn.execute("BEGIN IMMEDIATE")
            for stmt in _split_sql_statements(m.sql):
                if stmt:
                    conn.execute(stmt)
            now_utc = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                INSERT INTO schema_migrations (version, name, applied_at, checksum)
                VALUES (?, ?, ?, ?)
                """,
                (m.version, m.name, now_utc, m.checksum),
            )
            conn.commit()
            newly_applied.append(m.version)
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            raise MigrationError(
                f"Failed to apply migration {m.version} ({m.name}): {exc}"
            ) from exc

    return newly_applied
