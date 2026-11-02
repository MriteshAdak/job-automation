"""Generation worker implementation with RUN-01 Windows lock and bounded polling (GEN-01-S03/S08)."""

from __future__ import annotations

import logging
import random
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from job_automation.configuration import AppConfig, ResolvedPaths, load_config
from job_automation.contracts.enums import GenerationProcessing
from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import Generator, RendererDelivery, SalesforceGatewayV2
from job_automation.generation.admission import GenerationAdmitter
from job_automation.generation.coordinator import GenerationCoordinator
from job_automation.generation.errors import MissingComponentError
from job_automation.generation.ports import (
    ArtifactDeliverer,
    DocumentRenderer,
    DraftValidator,
    GenerationInputService,
    GenerationRequestSource,
    RequestStateProjector,
)
from job_automation.generation.polling import SalesforceGenerationRequestSource
from job_automation.generation.projection import SalesforceRequestStateProjector
from job_automation.generation.records import GenerationWorkerReport, StageStatus
from job_automation.generation.recovery import GenerationRecoveryManager
from job_automation.generation.request_mapping import RequestFieldMapping
from job_automation.generation.settings import GenerationSettings, load_generation_settings
from job_automation.orchestration.errors import LockContentionError
from job_automation.orchestration.records import OwnerKind
from job_automation.orchestration.windows_lock import LockToken, WindowsWorkerLock
from job_automation.salesforce.configuration import load_salesforce_settings
from job_automation.salesforce.gateway import SalesforceGatewayV2Client

if TYPE_CHECKING:
    from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


class GenerationWorker:
    """Manages exclusive Windows process locking, recovery, request polling, and coordination."""

    def __init__(
        self,
        config_path: str | Path | None = None,
        data_root: str | Path | None = None,
        gateway: SalesforceGatewayV2 | None = None,
        input_service: GenerationInputService | None = None,
        generator: Generator | None = None,
        validator: DraftValidator | None = None,
        renderer: DocumentRenderer | RendererDelivery | None = None,
        deliverer: ArtifactDeliverer | RendererDelivery | None = None,
        settings: GenerationSettings | None = None,
        mapping: RequestFieldMapping | None = None,
        engine: StorageEngine | None = None,
    ) -> None:
        self.config_path = config_path
        self.data_root = data_root
        self._gateway_override = gateway
        self.input_service = input_service
        self.generator = generator
        self.validator = validator
        self.renderer = renderer
        self.deliverer = deliverer
        self._settings_override = settings
        self._mapping_override = mapping
        self._engine_override = engine

    def _resolve_config_and_paths(self) -> tuple[AppConfig, ResolvedPaths]:
        return load_config(
            config_path=self.config_path,
            data_root_override=self.data_root,
        )

    def _build_gateway(self, app_config: AppConfig, paths: ResolvedPaths) -> SalesforceGatewayV2:
        if self._gateway_override is not None:
            return self._gateway_override
        if not paths.salesforce_settings_path or not paths.salesforce_settings_path.is_file():
            raise MissingComponentError("Salesforce settings file is missing or unconfigured")
        sf_settings = load_salesforce_settings(paths.salesforce_settings_path)
        return SalesforceGatewayV2Client(sf_settings)

    def run_once(
        self,
        stop_after_stage: str | None = None,
    ) -> GenerationWorkerReport:
        """Execute a single bounded cycle under exclusive Windows process lock."""
        app_config, paths = self._resolve_config_and_paths()
        lock = WindowsWorkerLock(paths.data_root)
        worker_attempt_id = uuid.uuid4()
        start_time = datetime.now(timezone.utc)

        # 1. Acquire exclusive lock BEFORE opening or migrating database
        token: LockToken | None = None
        try:
            token = lock.acquire_lock(owner_kind=OwnerKind.GENERATION, attempt_id=worker_attempt_id)
        except LockContentionError as exc:
            logger.warning("Generation worker lock busy on %s: %s", paths.data_root, exc)
            return GenerationWorkerReport(
                worker_attempt_id=worker_attempt_id,
                started_at=start_time,
                completed_at=datetime.now(timezone.utc),
                exit_code=3,
                errors=[
                    ClassifiedError.from_category(
                        category=ErrorCategory.CAPACITY,
                        message=f"Deployment worker lock busy: {exc}",
                        details=exc.details,
                    )
                ],
            )

        try:
            # 2. Open and migrate storage under held lock
            if self._engine_override is not None:
                engine = self._engine_override
            else:
                from job_automation.storage.engine import StorageEngine

                engine = StorageEngine.from_config(app_config, paths)
                engine.initialize_schema()

            # 3. Load generation settings
            if self._settings_override is not None:
                settings = self._settings_override
            elif paths.generation_settings_path and paths.generation_settings_path.is_file():
                settings = load_generation_settings(paths.generation_settings_path)
            else:
                settings = GenerationSettings()

            mapping = self._mapping_override or settings.mapping
            gateway = self._build_gateway(app_config, paths)

            return self._execute_cycle(
                engine=engine,
                gateway=gateway,
                settings=settings,
                mapping=mapping,
                worker_attempt_id=worker_attempt_id,
                start_time=start_time,
                stop_after_stage=stop_after_stage,
            )
        finally:
            if token is not None:
                token.release()

    def _execute_cycle(
        self,
        engine: StorageEngine,
        gateway: SalesforceGatewayV2,
        settings: GenerationSettings,
        mapping: RequestFieldMapping,
        worker_attempt_id: uuid.UUID,
        start_time: datetime,
        stop_after_stage: str | None = None,
    ) -> GenerationWorkerReport:
        report = GenerationWorkerReport(
            worker_attempt_id=worker_attempt_id,
            started_at=start_time,
            completed_at=datetime.now(timezone.utc),
            exit_code=0,
        )

        source = SalesforceGenerationRequestSource(
            gateway=gateway,
            mapping=mapping,
            org_id=mapping.expected_org_id,
            engine=engine,
        )
        projector = SalesforceRequestStateProjector(
            gateway=gateway,
            engine=engine,
            mapping=mapping,
        )
        admitter = GenerationAdmitter(engine=engine, mapping=mapping)
        recovery_mgr = GenerationRecoveryManager(
            engine=engine,
            projector=projector,
            source=source,
            settings=settings,
            mapping=mapping,
        )
        coordinator = GenerationCoordinator(
            engine=engine,
            projector=projector,
            input_service=self.input_service,
            generator=self.generator,
            validator=self.validator,
            renderer=self.renderer,
            deliverer=self.deliverer,
            settings=settings,
            mapping=mapping,
            worker_attempt_id=worker_attempt_id,
        )

        # Step 1: Recovery reconciliation
        try:
            rec_actions = recovery_mgr.reconcile_all()
            report.recovery_actions.extend(rec_actions)
        except Exception as exc:
            logger.exception("Error during recovery reconciliation: %s", exc)
            report.errors.append(ClassifiedError.from_category(ErrorCategory.TRANSIENT_SERVICE, f"Recovery failed: {exc}"))

        # Step 2: Poll remote Pending lane
        scanned_count = 0
        admitted_count = 0
        reused_count = 0
        completed_count = 0
        blocked_count = 0
        failed_count = 0

        continuation: str | None = None
        pages = 0
        max_pages = settings.limits.max_pages_per_cycle
        max_reqs = settings.limits.max_requests_per_cycle

        requests_to_process: list[Any] = []

        while pages < max_pages and len(requests_to_process) < max_reqs:
            obs_page, next_cont, err = source.poll_requests(
                lane="pending",
                continuation_token=continuation,
                limit=settings.limits.page_size,
            )
            pages += 1
            if err:
                report.errors.append(err)
                break

            scanned_count += len(obs_page)
            for obs in obs_page:
                if len(requests_to_process) >= max_reqs:
                    break
                existing_before = (
                    engine.generation_requests.get_by_salesforce_id(obs.canonical_salesforce_id)
                    if obs.canonical_salesforce_id
                    else None
                )
                admitted_req, adm_err = admitter.admit_observation(obs)
                if adm_err:
                    report.errors.append(adm_err)
                    if admitted_req and admitted_req.state == GenerationProcessing.FAILED:
                        failed_count += 1
                    else:
                        blocked_count += 1
                    continue

                if admitted_req is not None:
                    if existing_before is None:
                        admitted_count += 1
                    else:
                        reused_count += 1
                    requests_to_process.append(admitted_req)

            if not next_cont or not obs_page:
                break
            continuation = next_cont

        # Step 3: Also pick up local unfinished requests (e.g. from previous runs)
        local_unfinished = engine.generation_requests.get_unfinished_requests()
        for l_req in local_unfinished:
            if not any(r.request_id == l_req.request_id for r in requests_to_process):
                if len(requests_to_process) < max_reqs:
                    requests_to_process.append(l_req)

        # Step 4: Coordinate generation stages
        for req in requests_to_process:
            final_req, status, err = coordinator.process_request(req, stop_after_stage=stop_after_stage)
            if status == StageStatus.COMPLETED:
                completed_count += 1
            elif status == StageStatus.BLOCKED:
                blocked_count += 1
                report.pending_reasons[str(req.request_id)] = err.message if err else "Dependency blocked"
            elif status == StageStatus.FAILED:
                failed_count += 1
                if err:
                    report.errors.append(err)

        report.scanned_requests = scanned_count
        report.admitted_requests = admitted_count
        report.reused_requests = reused_count
        report.completed_requests = completed_count
        report.blocked_requests = blocked_count
        report.failed_requests = failed_count
        report.completed_at = datetime.now(timezone.utc)

        # Exit codes: 0 clean/completed, 4 blocked/pending, 1 fatal
        if blocked_count > 0:
            report.exit_code = 4
        elif report.errors:
            report.exit_code = 1
        else:
            report.exit_code = 0

        return report

    def run_watch(
        self,
        stop_after_stage: str | None = None,
        max_iterations: int | None = None,
    ) -> None:
        """Run foreground polling loop, releasing and reacquiring the lock between cycles."""
        iteration = 0
        app_config, paths = self._resolve_config_and_paths()
        if paths.generation_settings_path and paths.generation_settings_path.is_file():
            settings = load_generation_settings(paths.generation_settings_path)
        else:
            settings = self._settings_override or GenerationSettings()

        interval = settings.watch_poll_interval_seconds
        logger.info("Starting generation worker in watch mode (interval: %.1fs)", interval)

        try:
            while True:
                iteration += 1
                report = self.run_once(stop_after_stage=stop_after_stage)
                print(f"Cycle {iteration}: Completed={report.completed_requests}, Blocked={report.blocked_requests}, Failed={report.failed_requests} (exit: {report.exit_code})")

                if max_iterations is not None and iteration >= max_iterations:
                    break

                # Sleep and release lock between cycles, adding bounded jitter
                jitter = random.uniform(-0.1 * interval, 0.1 * interval)
                sleep_dur = max(1.0, interval + jitter)
                time.sleep(sleep_dur)
        except KeyboardInterrupt:
            logger.info("Watch mode interrupted by user (SIGINT/Ctrl+C)")
