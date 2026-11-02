"""End-to-end integration tests for coordinator stage 4 rendering via DocumentRendererAdapter (GEN-05-S06)."""
from __future__ import annotations

from types import SimpleNamespace
import pytest

from job_automation.contracts.enums import DocumentApproval, GenerationProcessing
from job_automation.generation.coordinator import GenerationCoordinator
from job_automation.generation.records import GenerationStage, StageStatus
from job_automation.generation.render_adapter import DocumentRendererAdapter
from job_automation.generation.render_service import RenderService
from job_automation.generation.settings import GenerationSettings
from tests.generation.validation.conftest import setup_validation


def test_coordinator_stage4_rendering_success(setup_validation):
    """Test coordinator executes rendering stage using DocumentRendererAdapter."""
    env = setup_validation()
    seal, _ = env.inputs.get_seal(env.request.request_id)
    manifest = seal.manifest

    render_service = RenderService(env.engine)
    renderer_adapter = DocumentRendererAdapter(render_service, env.engine)
    settings = GenerationSettings(required_formats=["docx"])

    coordinator = GenerationCoordinator(
        engine=env.engine,
        projector=SimpleNamespace(project_intent=lambda intent: True),
        validator=env.validator_adapter,
        renderer=renderer_adapter,
        settings=settings,
    )

    # 1. Validation Stage
    v_status, v_error = coordinator._coordinate_validation(env.request, env.draft, manifest)
    assert v_error is None
    assert v_status == StageStatus.COMPLETED

    # 2. Rendering Stage
    updated_req, r_status, r_error = coordinator._coordinate_rendering(env.request, env.draft)
    assert r_error is None
    assert r_status == StageStatus.COMPLETED
    assert updated_req.state == GenerationProcessing.UPLOAD_PENDING

    # Checkpoint completed
    render_chk = env.engine.generation_work.get_checkpoint(env.request.request_id, GenerationStage.RENDERING.value)
    assert render_chk is not None
    assert render_chk.status == StageStatus.COMPLETED

    # Delivery slot marked local_only
    slot = env.engine.generation_work.get_delivery_record(env.request.request_id, "docx")
    assert slot is not None
    assert slot.delivery_status == "local_only"

    # Artifact record saved with DRAFT approval status
    art = env.engine.artifacts.get_artifact(slot.artifact_id)
    assert art is not None
    assert art.delivery_status == "local_only"
    assert art.approval_status == DocumentApproval.DRAFT

    # Re-running coordinate rendering returns COMPLETED checkpoint immediately
    re_req, re_status, re_err = coordinator._coordinate_rendering(updated_req, env.draft)
    assert re_err is None
    assert re_status == StageStatus.COMPLETED


def test_coordinator_blocks_rendering_if_validation_denied(setup_validation):
    """Test coordinator blocks rendering if validation was not executed."""
    env = setup_validation()
    render_service = RenderService(env.engine)
    renderer_adapter = DocumentRendererAdapter(render_service, env.engine)
    settings = GenerationSettings(required_formats=["docx"])

    coordinator = GenerationCoordinator(
        engine=env.engine,
        projector=SimpleNamespace(project_intent=lambda intent: True),
        validator=env.validator_adapter,
        renderer=renderer_adapter,
        settings=settings,
    )

    req, r_status, r_error = coordinator._coordinate_rendering(env.request, env.draft)
    assert r_status == StageStatus.BLOCKED
    assert r_error is not None
    assert "Rendering blocked" in r_error.message
