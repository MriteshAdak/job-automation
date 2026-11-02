"""Tests for GenerationCoordinator integration and checkpoint recovery (GEN-04-S06)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from job_automation.contracts.artifacts import Artifact
from job_automation.contracts.enums import DocumentApproval, GenerationProcessing
from job_automation.generation.coordinator import GenerationCoordinator
from job_automation.generation.records import GenerationStage, StageStatus


class FakeRenderer:
    def __init__(self):
        self.render_calls = []

    def render_document(self, draft, fmt, dest_path, op_id):
        self.render_calls.append((draft, fmt, dest_path, op_id))
        art = Artifact(
            artifact_id=uuid.uuid4(),
            request_id=draft.request_id,
            format=fmt,
            artifact_version=1,
            local_path=dest_path,
            content_hash="sha256:" + "a" * 64,
            size_bytes=1024,
            delivery_status="local_only",
            approval_status=DocumentApproval.DRAFT,
            created_at=datetime.now(timezone.utc),
        )
        return art, None


def test_coordinator_validation_and_rendering_success(setup_validation):
    env = setup_validation()
    renderer = FakeRenderer()

    seal, _ = env.inputs.get_seal(env.request.request_id)
    manifest = seal.manifest

    coordinator = GenerationCoordinator(
        engine=env.engine,
        projector=SimpleNamespace(project_intent=lambda intent: True),
        validator=env.validator_adapter,
        renderer=renderer,
    )

    # 1. Validation Stage
    status, error = coordinator._coordinate_validation(env.request, env.draft, manifest)
    assert error is None
    assert status == StageStatus.COMPLETED

    val_chk = env.engine.generation_work.get_checkpoint(env.request.request_id, GenerationStage.VALIDATION.value)
    assert val_chk is not None
    assert val_chk.status == StageStatus.COMPLETED
    assert val_chk.checkpoint_data.get("report_ref") is not None

    # 2. Rendering Stage
    req, r_status, r_error = coordinator._coordinate_rendering(env.request, env.draft)
    assert r_error is None
    assert r_status == StageStatus.COMPLETED
    assert len(renderer.render_calls) > 0


def test_coordinator_blocks_rendering_if_validation_incomplete(setup_validation):
    env = setup_validation()
    renderer = FakeRenderer()

    coordinator = GenerationCoordinator(
        engine=env.engine,
        projector=SimpleNamespace(project_intent=lambda intent: True),
        validator=env.validator_adapter,
        renderer=renderer,
    )

    # Try rendering without running validation stage
    req, r_status, r_error = coordinator._coordinate_rendering(env.request, env.draft)
    assert r_status == StageStatus.BLOCKED
    assert r_error is not None
    assert "Rendering blocked" in r_error.message
    assert len(renderer.render_calls) == 0


def test_coordinator_blocks_rendering_if_draft_tampered(setup_validation):
    env = setup_validation()
    renderer = FakeRenderer()

    seal, _ = env.inputs.get_seal(env.request.request_id)
    manifest = seal.manifest

    coordinator = GenerationCoordinator(
        engine=env.engine,
        projector=SimpleNamespace(project_intent=lambda intent: True),
        validator=env.validator_adapter,
        renderer=renderer,
    )

    # Run validation on original draft
    status, error = coordinator._coordinate_validation(env.request, env.draft, manifest)
    assert status == StageStatus.COMPLETED

    # Alter draft
    tampered_draft = env.draft.model_copy(update={"document_version": "draft:tampered"})

    # Rendering tampered draft must be blocked
    req, r_status, r_error = coordinator._coordinate_rendering(env.request, tampered_draft)
    assert r_status == StageStatus.BLOCKED
    assert r_error is not None
    assert len(renderer.render_calls) == 0


def test_coordinator_repairs_missing_checkpoint_from_committed_report(setup_validation):
    env = setup_validation()
    seal, _ = env.inputs.get_seal(env.request.request_id)
    manifest = seal.manifest

    coordinator = GenerationCoordinator(
        engine=env.engine,
        projector=SimpleNamespace(project_intent=lambda intent: True),
        validator=env.validator_adapter,
    )

    # 1. Directly validate content and commit report, but do NOT save checkpoint (simulating crash before checkpoint save)
    res = env.validation_service.validate_content(env.request.request_id, env.draft)
    assert res.report is not None

    # Check that no validation checkpoint exists yet
    chk = env.engine.generation_work.get_checkpoint(env.request.request_id, GenerationStage.VALIDATION.value)
    assert chk is None

    # 2. Coordinator runs validation: should repair checkpoint from committed report without error
    status, error = coordinator._coordinate_validation(env.request, env.draft, manifest)
    assert error is None
    assert status == StageStatus.COMPLETED

    repaired_chk = env.engine.generation_work.get_checkpoint(env.request.request_id, GenerationStage.VALIDATION.value)
    assert repaired_chk is not None
    assert repaired_chk.status == StageStatus.COMPLETED

