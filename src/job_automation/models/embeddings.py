"""Embedding harness for local model execution (LLM-01-S05, S06).

Coordinates:
- Preflight validation of batch bounds and text emptiness.
- Context budget check across ordered texts without completion reserve.
- Canonical fingerprinting of ordered texts.
- Bounded HTTP execution against local runtime (/api/embed).
- Strict vector validation: exact 1:1 count, order preservation, finite floats, consistent dimension.
- Complete audit recording linking success or failure by call ID.
"""

from __future__ import annotations

import json
import math
import uuid
from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import EmbeddingResponse
from job_automation.contracts.models import TokenUsage
from job_automation.models.audit import AuditManager
from job_automation.models.budget import ContextBudgetManager
from job_automation.models.configuration import ModelProviderSettings
from job_automation.models.errors import (
    classify_http_status,
    classify_transport_error,
)
from job_automation.models.fingerprints import compute_embedding_fingerprint
from job_automation.models.ports import Clock, ModelTransport, Sleeper
from job_automation.models.records import AttemptAuditRecord, LogicalCallAuditRecord
from job_automation.models.retry import RetryController


class EmbeddingHarness:
    """Execution harness for ModelProvider.embed."""

    def __init__(
        self,
        settings: ModelProviderSettings,
        transport: ModelTransport,
        budget_manager: ContextBudgetManager,
        audit_manager: AuditManager,
        clock: Clock,
        sleeper: Sleeper,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.budget_manager = budget_manager
        self.audit_manager = audit_manager
        self.clock = clock
        self.sleeper = sleeper

    def execute(
        self,
        texts: list[str],
        model: str,
    ) -> tuple[EmbeddingResponse | None, ClassifiedError | None]:
        """Generate vector embeddings with local embedding model."""
        start_mono = self.clock.monotonic()
        start_utc = self.clock.now_utc()
        call_id = uuid.uuid4()
        attempts: list[AttemptAuditRecord] = []

        # ── 1. Preflight Validation & Fingerprint ─────────────────────────────
        if not isinstance(texts, list):
            err = ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                "Embedding texts must be a list of strings",
                details={"call_id": str(call_id)},
            )
            return self._record_and_return_failure(call_id, texts, model, err, start_utc, start_mono, attempts)

        # Context budget check
        _, budget_err = self.budget_manager.check_embedding_budget(texts, model)
        if budget_err is not None:
            budget_details = dict(budget_err.details or {})
            budget_details["call_id"] = str(call_id)
            budget_err = ClassifiedError.from_category(
                budget_err.category,
                budget_err.message,
                field_path=budget_err.field_path,
                details=budget_details,
            )
            return self._record_and_return_failure(call_id, texts, model, budget_err, start_utc, start_mono, attempts)

        fingerprint = compute_embedding_fingerprint(texts)
        model_caps = self.settings.models.get(model)
        expected_dim = model_caps.dimension if model_caps is not None else None
        context_limit = model_caps.max_context_tokens if model_caps is not None else self.settings.default_context_ceiling

        wire_payload = {
            "model": model,
            "input": list(texts),
        }

        retry_ctrl = RetryController(self.settings, self.clock, self.sleeper)
        last_error: ClassifiedError | None = None
        validated_vectors: list[list[float]] | None = None
        observed_model: str = model
        observed_digest: str | None = None
        observed_dim: int = 0
        final_usage: TokenUsage | None = None

        # ── 2. Transport Attempt Loop ────────────────────────────────────────
        while retry_ctrl.can_attempt():
            purpose = "retry_service" if retry_ctrl.total_attempts > 0 else "initial"
            att_num = retry_ctrl.record_attempt(purpose)
            att_start_mono = self.clock.monotonic()
            att_start_utc = self.clock.now_utc()
            timeout = min(self.settings.read_timeout_seconds, retry_ctrl.remaining_deadline())

            if timeout <= 0.0:
                last_error = ClassifiedError.from_category(
                    ErrorCategory.TRANSIENT_SERVICE,
                    "Execution deadline exceeded before embedding attempt",
                    details={"call_id": str(call_id)},
                )
                break

            try:
                status, headers, body_bytes = self.transport.post(
                    "/api/embed",
                    wire_payload,
                    timeout_seconds=timeout,
                )
            except Exception as exc:
                att_end_mono = self.clock.monotonic()
                att_end_utc = self.clock.now_utc()
                last_error = classify_transport_error(exc)
                attempts.append(
                    AttemptAuditRecord(
                        call_id=call_id,
                        attempt_number=att_num,
                        purpose=purpose,
                        start_time_utc=att_start_utc,
                        end_time_utc=att_end_utc,
                        duration_ms=(att_end_mono - att_start_mono) * 1000.0,
                        http_status=None,
                        outcome=str(last_error.category),
                    )
                )
                if retry_ctrl.should_retry_error(last_error):
                    if not retry_ctrl.execute_backoff(att_num):
                        break
                    continue
                break

            att_end_mono = self.clock.monotonic()
            att_end_utc = self.clock.now_utc()
            att_duration = (att_end_mono - att_start_mono) * 1000.0

            if status != 200:
                last_error = classify_http_status(status, body_bytes, headers)
                attempts.append(
                    AttemptAuditRecord(
                        call_id=call_id,
                        attempt_number=att_num,
                        purpose=purpose,
                        start_time_utc=att_start_utc,
                        end_time_utc=att_end_utc,
                        duration_ms=att_duration,
                        http_status=status,
                        outcome=str(last_error.category),
                    )
                )
                if retry_ctrl.should_retry_error(last_error):
                    retry_after = headers.get("retry-after")
                    if not retry_ctrl.execute_backoff(att_num, retry_after):
                        break
                    continue
                break

            # Parse envelope
            envelope_dict: dict[str, Any] = {}
            try:
                envelope_dict = json.loads(body_bytes.decode("utf-8", errors="replace"))
                if not isinstance(envelope_dict, dict):
                    raise ValueError("Envelope must be a JSON object")
            except Exception as exc:
                last_error = ClassifiedError.from_category(
                    ErrorCategory.MODEL_OUTPUT,
                    f"Invalid wire envelope from embedding runtime: {exc}",
                )
                attempts.append(
                    AttemptAuditRecord(
                        call_id=call_id,
                        attempt_number=att_num,
                        purpose=purpose,
                        start_time_utc=att_start_utc,
                        end_time_utc=att_end_utc,
                        duration_ms=att_duration,
                        http_status=status,
                        outcome=str(ErrorCategory.MODEL_OUTPUT),
                    )
                )
                break

            observed_model = str(envelope_dict.get("model", model))
            observed_digest = envelope_dict.get("digest")

            # Check pinned digest
            if model_caps and model_caps.expected_digest and observed_digest:
                if model_caps.expected_digest != observed_digest:
                    last_error = ClassifiedError.from_category(
                        ErrorCategory.MODEL_OUTPUT,
                        f"Observed embedding model digest '{observed_digest}' does not match expected '{model_caps.expected_digest}'",
                    )
                    break

            raw_embeddings = envelope_dict.get("embeddings")
            if not isinstance(raw_embeddings, list):
                last_error = ClassifiedError.from_category(
                    ErrorCategory.MODEL_OUTPUT,
                    "Embedding response missing 'embeddings' array",
                )
                attempts.append(
                    AttemptAuditRecord(
                        call_id=call_id,
                        attempt_number=att_num,
                        purpose=purpose,
                        start_time_utc=att_start_utc,
                        end_time_utc=att_end_utc,
                        duration_ms=att_duration,
                        http_status=status,
                        outcome=str(ErrorCategory.MODEL_OUTPUT),
                    )
                )
                break

            # ── 3. Validate Vectors ──────────────────────────────────────────
            if len(raw_embeddings) != len(texts):
                last_error = ClassifiedError.from_category(
                    ErrorCategory.MODEL_OUTPUT,
                    f"Vector count mismatch: input had {len(texts)} texts, but runtime returned {len(raw_embeddings)} vectors",
                )
                attempts.append(
                    AttemptAuditRecord(
                        call_id=call_id,
                        attempt_number=att_num,
                        purpose=purpose,
                        start_time_utc=att_start_utc,
                        end_time_utc=att_end_utc,
                        duration_ms=att_duration,
                        http_status=status,
                        outcome=str(ErrorCategory.MODEL_OUTPUT),
                    )
                )
                break

            dim = -1
            clean_vectors: list[list[float]] = []
            valid_format = True

            for v_idx, vec in enumerate(raw_embeddings):
                if not isinstance(vec, list) or len(vec) == 0:
                    last_error = ClassifiedError.from_category(
                        ErrorCategory.MODEL_OUTPUT,
                        f"Vector at index {v_idx} is empty or not a list",
                    )
                    valid_format = False
                    break

                if dim == -1:
                    dim = len(vec)
                elif len(vec) != dim:
                    last_error = ClassifiedError.from_category(
                        ErrorCategory.MODEL_OUTPUT,
                        f"Inconsistent vector dimensions: vector at index {v_idx} has {len(vec)}, expected {dim}",
                    )
                    valid_format = False
                    break

                # Validate elements are finite numbers, strictly excluding booleans
                clean_vec: list[float] = []
                for e_idx, elem in enumerate(vec):
                    if isinstance(elem, bool) or not isinstance(elem, (int, float)) or not math.isfinite(elem):
                        last_error = ClassifiedError.from_category(
                            ErrorCategory.MODEL_OUTPUT,
                            f"Vector at index {v_idx}[{e_idx}] contains non-finite or non-numeric value '{elem}'",
                        )
                        valid_format = False
                        break
                    clean_vec.append(float(elem))

                if not valid_format:
                    break
                clean_vectors.append(clean_vec)

            if not valid_format:
                attempts.append(
                    AttemptAuditRecord(
                        call_id=call_id,
                        attempt_number=att_num,
                        purpose=purpose,
                        start_time_utc=att_start_utc,
                        end_time_utc=att_end_utc,
                        duration_ms=att_duration,
                        http_status=status,
                        outcome=str(ErrorCategory.MODEL_OUTPUT),
                    )
                )
                break

            # Check expected dimension if known
            if expected_dim is not None and dim != expected_dim:
                last_error = ClassifiedError.from_category(
                    ErrorCategory.MODEL_OUTPUT,
                    f"Observed vector dimension {dim} does not match configured dimension {expected_dim} for model '{model}'",
                )
                attempts.append(
                    AttemptAuditRecord(
                        call_id=call_id,
                        attempt_number=att_num,
                        purpose=purpose,
                        start_time_utc=att_start_utc,
                        end_time_utc=att_end_utc,
                        duration_ms=att_duration,
                        http_status=status,
                        outcome=str(ErrorCategory.MODEL_OUTPUT),
                    )
                )
                break

            # Extract usage if present
            prompt_eval = envelope_dict.get("prompt_eval_count")
            if prompt_eval is not None:
                final_usage = TokenUsage(
                    prompt_tokens=prompt_eval,
                    completion_tokens=0,
                    total_tokens=prompt_eval,
                )

            observed_dim = dim
            validated_vectors = clean_vectors
            attempts.append(
                AttemptAuditRecord(
                    call_id=call_id,
                    attempt_number=att_num,
                    purpose=purpose,
                    start_time_utc=att_start_utc,
                    end_time_utc=att_end_utc,
                    duration_ms=att_duration,
                    http_status=status,
                    outcome="success",
                    token_usage=final_usage,
                )
            )
            last_error = None
            break

        # ── 4. Build Final Result & Audit Record ─────────────────────────────
        end_mono = self.clock.monotonic()
        end_utc = self.clock.now_utc()
        total_latency = (end_mono - start_mono) * 1000.0

        if last_error is None and validated_vectors is not None:
            resp = EmbeddingResponse(
                vectors=validated_vectors,
                model_identifier=observed_model,
                dimension=observed_dim,
                call_id=call_id,
                model_digest=observed_digest,
                token_usage=final_usage,
            )
            audit_record = LogicalCallAuditRecord(
                call_id=call_id,
                operation_type="embedding",
                requested_model=model,
                requested_digest=model_caps.expected_digest if model_caps else None,
                observed_model=observed_model,
                observed_digest=observed_digest,
                input_format_version="v1",
                context_limit=context_limit,
                input_fingerprint=fingerprint,
                start_time_utc=start_utc,
                end_time_utc=end_utc,
                latency_ms=total_latency,
                token_usage=final_usage,
                outcome="success",
                attempts_count=len(attempts),
                attempts=attempts,
            )
            self.audit_manager.record(audit_record)
            return resp, None

        final_err = last_error or ClassifiedError.from_category(
            ErrorCategory.TRANSIENT_SERVICE,
            "Exhausted allowed transport attempts for embeddings without completion",
        )
        final_details = dict(final_err.details or {})
        final_details["call_id"] = str(call_id)
        final_err = ClassifiedError.from_category(
            final_err.category,
            final_err.message,
            field_path=final_err.field_path,
            details=final_details,
        )

        audit_record = LogicalCallAuditRecord(
            call_id=call_id,
            operation_type="embedding",
            requested_model=model,
            requested_digest=model_caps.expected_digest if model_caps else None,
            input_format_version="v1",
            context_limit=context_limit,
            input_fingerprint=fingerprint if "fingerprint" in locals() else "unknown",
            start_time_utc=start_utc,
            end_time_utc=end_utc,
            latency_ms=total_latency,
            token_usage=final_usage,
            outcome=str(final_err.category),
            attempts_count=len(attempts),
            attempts=attempts,
        )
        self.audit_manager.record(audit_record)
        return None, final_err

    def _record_and_return_failure(
        self,
        call_id: uuid.UUID,
        texts: list[str],
        model: str,
        error: ClassifiedError,
        start_utc: Any,
        start_mono: float,
        attempts: list[AttemptAuditRecord],
    ) -> tuple[EmbeddingResponse | None, ClassifiedError | None]:
        end_mono = self.clock.monotonic()
        end_utc = self.clock.now_utc()
        latency = (end_mono - start_mono) * 1000.0

        fingerprint = (
            compute_embedding_fingerprint(texts)
            if isinstance(texts, list) and texts
            else "unknown"
        )

        audit_record = LogicalCallAuditRecord(
            call_id=call_id,
            operation_type="embedding",
            requested_model=model,
            input_format_version="v1",
            context_limit=self.settings.default_context_ceiling,
            input_fingerprint=fingerprint,
            start_time_utc=start_utc,
            end_time_utc=end_utc,
            latency_ms=latency,
            outcome=str(error.category),
            attempts_count=len(attempts),
            attempts=attempts,
        )
        self.audit_manager.record(audit_record)
        return None, error
