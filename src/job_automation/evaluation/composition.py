"""Evaluation environment composition and publication firewall (EVAL-01-S03).

Enforces:
- Absolute prevention of Salesforce publication side effects.
- Dedicated, isolated repository and workspace instantiation.
- Rejection of publication flags, synchronization services, and outbox handlers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from job_automation.evaluation.errors import PublicationAttemptBlockedError
from job_automation.evaluation.ports import assert_no_publication_authority
from job_automation.evaluation.repository import EvaluationRepository
from job_automation.evaluation.settings import EvaluationSettings
from job_automation.evaluation.workspace import EvaluationWorkspace


@dataclass
class EvaluationEnvironment:
    """Encapsulates isolated storage, workspace, and configuration for evaluation."""

    settings: EvaluationSettings
    workspace: EvaluationWorkspace
    repository: EvaluationRepository

    def close(self) -> None:
        """Close open resources."""
        self.repository.close()


def create_evaluation_environment(settings: EvaluationSettings) -> EvaluationEnvironment:
    """Create and validate an isolated evaluation environment.

    Guarantees:
    - Zero Salesforce gateway, client, or sync service instantiation.
    - Zero outbox queueing or candidate backup side effects.
    - Workspace directories and database initialized strictly beneath eval_root.
    """
    if getattr(settings, "enable_sync", False):
        raise PublicationAttemptBlockedError(
            "enable_sync=True is strictly forbidden in evaluation. "
            "Evaluation runs cannot publish or sync to Salesforce."
        )

    assert_no_publication_authority(settings)

    workspace = EvaluationWorkspace.from_settings(settings)
    workspace.initialize_directories()

    repository = EvaluationRepository(workspace.db_path)

    return EvaluationEnvironment(
        settings=settings,
        workspace=workspace,
        repository=repository,
    )

