"""Structured generation harness for local model execution (LLM-01-S04, S06).

Coordinates:
- Preflight input fingerprint verification, schema resolution, and context budgeting.
- Bounded HTTP POST execution against local runtime (/api/generate).
- Wire envelope inspection, completion status validation, and strict JSON parsing.
- Schema compliance checking without value coercion or field dropping.
- Unified retry control with bounded backoff and audit recording.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.models import ModelCall, ModelResult, TokenUsage
from job_automation.models.audit import AuditManager
from job_automation.models.budget import ContextBudgetManager
from job_automation.models.configuration import ModelProviderSettings
from job_automation.models.errors import (
    classify_http_status,
    classify_transport_error,
)
from job_automation.models.ports import Clock, InputResolver, ModelTransport, Sleeper
from job_automation.models.records import AttemptAuditRecord, LogicalCallAuditRecord
from job_automation.models.retry import RetryController
from job_automation.models.schemas import (
    LocalSchemaRegistry,
    RegisteredSchema,
    parse_strict_json,
    validate_against_schema,
)
from job_automation.models.settings import validate_generation_settings


class GenerationHarness:
    """Execution harness for ModelProvider.generate."""

    def __init__(
        self,
        settings: ModelProviderSettings,
        transport: ModelTransport,
        input_resolver: InputResolver,
        schema_registry: LocalSchemaRegistry,
        budget_manager: ContextBudgetManager,
        audit_manager: AuditManager,
        clock: Clock,
        sleeper: Sleeper,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.input_resolver = input_resolver
        self.schema_registry = schema_registry
        self.budget_manager = budget_manager
        self.audit_manager = audit_manager
        self.clock = clock
        self.sleeper = sleeper

    def execute(self, call: ModelCall) -> ModelResult:
        """Execute structured generation call with complete preflight, validation, and audit."""
        start_mono = self.clock.monotonic()
        start_utc = self.clock.now_utc()
        attempts: list[AttemptAuditRecord] = []

        # ── 1. Preflight Resolution & Validation ─────────────────────────────
        # Resolve bound input
        bound_input = self.input_resolver.resolve_generation_input(call.call_id)
        if bound_input is None:
            preflight_err = ClassifiedError.from_category(
                ErrorCategory.UNSUPPORTED_INPUT,
                f"No immutable input bound for call ID {call.call_id}",
                details={"call_id": str(call.call_id)},
            )
            return self._record_and_return_failure(
                call, preflight_err, start_utc, start_mono, attempts
            )

        # Verify fingerprint integrity
        if bound_input.input_fingerprint != call.input_fingerprint:
            preflight_err = ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                f"Input fingerprint mismatch for call ID {call.call_id}: call declares {call.input_fingerprint}, bound input computed {bound_input.input_fingerprint}",
                field_path="input_fingerprint",
                details={"declared": call.input_fingerprint, "computed": bound_input.input_fingerprint},
            )
            return self._record_and_return_failure(
                call, preflight_err, start_utc, start_mono, attempts
            )

        # Resolve requested schema
        if not call.requested_schema:
            preflight_err = ClassifiedError.from_category(
                ErrorCategory.VALIDATION,
                "Structured generation requires a non-null requested_schema",
                field_path="requested_schema",
            )
            return self._record_and_return_failure(
                call, preflight_err, start_utc, start_mono, attempts
            )

        try:
            schema = self.schema_registry.resolve(call.requested_schema)
        except ValueError as exc:
            preflight_err = ClassifiedError.from_category(
                ErrorCategory.MISSING_CONFIGURATION,
                f"Requested output schema could not be resolved: {exc}",
                field_path="requested_schema",
            )
            return self._record_and_return_failure(
                call, preflight_err, start_utc, start_mono, attempts
            )

        # Validate generation settings allowlist
        effective_options, settings_err = validate_generation_settings(call.generation_settings)
        if settings_err is not None:
            return self._record_and_return_failure(
                call, settings_err, start_utc, start_mono, attempts, schema=schema
            )

        # Context budget check
        input_tokens, effective_ceiling, budget_err = self.budget_manager.check_generation_budget(
            prompt=bound_input.prompt,
            system_prompt=bound_input.system_prompt,
            requested_context_limit=call.context_limit,
            model_identifier=call.model_identifier,
        )
        if budget_err is not None:
            return self._record_and_return_failure(
                call, budget_err, start_utc, start_mono, attempts, schema=schema, effective_settings=effective_options
            )

        # ── 2. Prepare Wire Request ──────────────────────────────────────────
        effective_options["num_ctx"] = effective_ceiling
        wire_payload: dict[str, Any] = {
            "model": call.model_identifier,
            "prompt": bound_input.prompt,
            "stream": False,
            "format": schema.json_schema,
            "options": effective_options,
        }
        if bound_input.system_prompt:
            wire_payload["system"] = bound_input.system_prompt

        retry_ctrl = RetryController(self.settings, self.clock, self.sleeper)
        last_error: ClassifiedError | None = None
        validated_dict: dict[str, Any] | None = None
        raw_output_text: str | None = None
        observed_model: str = call.model_identifier
        observed_digest: str | None = None
        final_usage: TokenUsage | None = None

        # ── 3. Transport Attempt Loop ────────────────────────────────────────
        while retry_ctrl.can_attempt():
            is_regeneration = (
                last_error is not None and last_error.category == ErrorCategory.MODEL_OUTPUT
            )
            purpose = "regeneration_malformed_output" if is_regeneration else (
                "retry_service" if retry_ctrl.total_attempts > 0 else "initial"
            )

            att_num = retry_ctrl.record_attempt(purpose)
            att_start_mono = self.clock.monotonic()
            att_start_utc = self.clock.now_utc()
            timeout = min(self.settings.read_timeout_seconds, retry_ctrl.remaining_deadline())

            if timeout <= 0.0:
                last_error = ClassifiedError.from_category(
                    ErrorCategory.TRANSIENT_SERVICE,
                    "Total execution deadline exceeded before attempt start",
                    details={"attempts": att_num},
                )
                break

            try:
                status, headers, body_bytes = self.transport.post(
                    "/api/generate",
                    wire_payload,
                    timeout_seconds=timeout,
                )
            except Exception as exc:
                att_end_mono = self.clock.monotonic()
                att_end_utc = self.clock.now_utc()
                last_error = classify_transport_error(exc)
                attempts.append(
                    AttemptAuditRecord(
                        call_id=call.call_id,
                        attempt_number=att_num,
                        purpose=purpose,
                        start_time_utc=att_start_utc,
                        end_time_utc=att_end_utc,
                        duration_ms=(att_end_mono - att_start_mono) * 1000.0,
                        http_status=None,
                        outcome=str(last_error.category),
                        error_code=last_error.details.get("reason") if last_error.details else None,
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
                        call_id=call.call_id,
                        attempt_number=att_num,
                        purpose=purpose,
                        start_time_utc=att_start_utc,
                        end_time_utc=att_end_utc,
                        duration_ms=att_duration,
                        http_status=status,
                        outcome=str(last_error.category),
                        error_code=f"http_{status}",
                    )
                )
                if retry_ctrl.should_retry_error(last_error):
                    retry_after = headers.get("retry-after")
                    if not retry_ctrl.execute_backoff(att_num, retry_after):
                        break
                    continue
                break

            # HTTP 200: Inspect outer envelope
            envelope_dict: dict[str, Any] = {}
            try:
                envelope_dict = json.loads(body_bytes.decode("utf-8", errors="replace"))
                if not isinstance(envelope_dict, dict):
                    raise ValueError("Envelope must be a JSON object")
            except Exception as exc:
                last_error = ClassifiedError.from_category(
                    ErrorCategory.MODEL_OUTPUT,
                    f"Invalid wire envelope from local model service: {exc}",
                )
                attempts.append(
                    AttemptAuditRecord(
                        call_id=call.call_id,
                        attempt_number=att_num,
                        purpose=purpose,
                        start_time_utc=att_start_utc,
                        end_time_utc=att_end_utc,
                        duration_ms=att_duration,
                        http_status=status,
                        outcome=str(ErrorCategory.MODEL_OUTPUT),
                        error_code="malformed_wire_envelope",
                    )
                )
                if retry_ctrl.should_regenerate_malformed():
                    if not retry_ctrl.execute_backoff(att_num):
                        break
                    continue
                break

            # Check completion status and done_reason
            done = envelope_dict.get("done", False)
            done_reason = envelope_dict.get("done_reason")
            if done_reason == "length":
                last_error = ClassifiedError.from_category(
                    ErrorCategory.CONTEXT_BUDGET,
                    "Model runtime context window exhausted during generation (done_reason='length')",
                    details={"done_reason": "length"},
                )
                attempts.append(
                    AttemptAuditRecord(
                        call_id=call.call_id,
                        attempt_number=att_num,
                        purpose=purpose,
                        start_time_utc=att_start_utc,
                        end_time_utc=att_end_utc,
                        duration_ms=att_duration,
                        http_status=status,
                        outcome=str(ErrorCategory.CONTEXT_BUDGET),
                        error_code="context_length_exhausted",
                    )
                )
                # Context limit error is non-recoverable with same input
                break

            if not done:
                last_error = ClassifiedError.from_category(
                    ErrorCategory.MODEL_OUTPUT,
                    "Model generation stream terminated prematurely (done is False)",
                )
                attempts.append(
                    AttemptAuditRecord(
                        call_id=call.call_id,
                        attempt_number=att_num,
                        purpose=purpose,
                        start_time_utc=att_start_utc,
                        end_time_utc=att_end_utc,
                        duration_ms=att_duration,
                        http_status=status,
                        outcome=str(ErrorCategory.MODEL_OUTPUT),
                        error_code="incomplete_completion",
                    )
                )
                if retry_ctrl.should_regenerate_malformed():
                    if not retry_ctrl.execute_backoff(att_num):
                        break
                    continue
                break

            # Extract model provenance
            observed_model = str(envelope_dict.get("model", call.model_identifier))
            observed_digest = envelope_dict.get("digest")

            # Check pinned digest mismatch if specified
            if call.model_digest is not None and observed_digest is not None:
                if call.model_digest != observed_digest:
                    last_error = ClassifiedError.from_category(
                        ErrorCategory.MODEL_OUTPUT,
                        f"Observed model digest '{observed_digest}' does not match requested digest '{call.model_digest}'",
                        details={"requested": call.model_digest, "observed": observed_digest},
                    )
                    attempts.append(
                        AttemptAuditRecord(
                            call_id=call.call_id,
                            attempt_number=att_num,
                            purpose=purpose,
                            start_time_utc=att_start_utc,
                            end_time_utc=att_end_utc,
                            duration_ms=att_duration,
                            http_status=status,
                            outcome=str(ErrorCategory.MODEL_OUTPUT),
                            error_code="digest_mismatch",
                        )
                    )
                    break

            # Extract token usage
            p_tokens = envelope_dict.get("prompt_eval_count")
            c_tokens = envelope_dict.get("eval_count")
            if p_tokens is not None or c_tokens is not None:
                t_tokens = (p_tokens or 0) + (c_tokens or 0)
                final_usage = TokenUsage(
                    prompt_tokens=p_tokens,
                    completion_tokens=c_tokens,
                    total_tokens=t_tokens,
                )

            # Strict JSON parsing of generated content
            resp_content = envelope_dict.get("response", "")
            try:
                parsed_json = parse_strict_json(resp_content)
            except ValueError as exc:
                last_error = ClassifiedError.from_category(
                    ErrorCategory.MODEL_OUTPUT,
                    f"Malformed JSON output from model: {exc}",
                    details={"error_detail": str(exc)},
                )
                attempts.append(
                    AttemptAuditRecord(
                        call_id=call.call_id,
                        attempt_number=att_num,
                        purpose=purpose,
                        start_time_utc=att_start_utc,
                        end_time_utc=att_end_utc,
                        duration_ms=att_duration,
                        http_status=status,
                        outcome=str(ErrorCategory.MODEL_OUTPUT),
                        error_code="malformed_json",
                        token_usage=final_usage,
                    )
                )
                if retry_ctrl.should_regenerate_malformed():
                    if not retry_ctrl.execute_backoff(att_num):
                        break
                    continue
                break

            # Schema validation
            validated_obj, validation_issues = validate_against_schema(parsed_json, schema)
            if validation_issues:
                issue_summary = "; ".join(issue.message for issue in validation_issues[:3])
                last_error = ClassifiedError.from_category(
                    ErrorCategory.MODEL_OUTPUT,
                    f"Model output violates registered schema '{schema.schema_id}': {issue_summary}",
                    details={"issues_count": len(validation_issues)},
                )
                attempts.append(
                    AttemptAuditRecord(
                        call_id=call.call_id,
                        attempt_number=att_num,
                        purpose=purpose,
                        start_time_utc=att_start_utc,
                        end_time_utc=att_end_utc,
                        duration_ms=att_duration,
                        http_status=status,
                        outcome=str(ErrorCategory.MODEL_OUTPUT),
                        error_code="schema_validation_failed",
                        token_usage=final_usage,
                    )
                )
                if retry_ctrl.should_regenerate_malformed():
                    if not retry_ctrl.execute_backoff(att_num):
                        break
                    continue
                break

            # Validation succeeded!
            validated_dict = validated_obj
            raw_output_text = resp_content
            attempts.append(
                AttemptAuditRecord(
                    call_id=call.call_id,
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

        if last_error is None and validated_dict is not None:
            result = ModelResult(
                call_id=call.call_id,
                model_identifier=observed_model,
                model_digest=observed_digest,
                output_text=raw_output_text,
                parsed_output=validated_dict,
                error=None,
                latency_ms=total_latency,
                token_usage=final_usage,
            )
            outcome = "success"
            err_code = None
        else:
            final_err = last_error or ClassifiedError.from_category(
                ErrorCategory.TRANSIENT_SERVICE,
                "Exhausted allowed transport attempts without successful completion",
            )
            result = ModelResult(
                call_id=call.call_id,
                model_identifier=call.model_identifier,
                model_digest=None,
                output_text=None,
                parsed_output=None,
                error=final_err,
                latency_ms=total_latency,
                token_usage=final_usage,
            )
            outcome = str(final_err.category)
            err_code = final_err.details.get("reason") if final_err.details else None

        audit_record = LogicalCallAuditRecord(
            call_id=call.call_id,
            operation_type=call.operation_type,
            requested_model=call.model_identifier,
            requested_digest=call.model_digest,
            observed_model=observed_model if outcome == "success" else None,
            observed_digest=observed_digest if outcome == "success" else None,
            prompt_version=call.prompt_version,
            system_prompt_version=call.system_prompt_version,
            schema_id=schema.schema_id if schema else None,
            schema_version=schema.version if schema else None,
            effective_settings=effective_options,
            context_limit=call.context_limit,
            input_fingerprint=call.input_fingerprint,
            start_time_utc=start_utc,
            end_time_utc=end_utc,
            latency_ms=total_latency,
            token_usage=final_usage,
            outcome=outcome,
            error_code=err_code,
            attempts_count=len(attempts),
            attempts=attempts,
        )
        self.audit_manager.record(audit_record)
        return result

    def _record_and_return_failure(
        self,
        call: ModelCall,
        error: ClassifiedError,
        start_utc: Any,
        start_mono: float,
        attempts: list[AttemptAuditRecord],
        schema: RegisteredSchema | None = None,
        effective_settings: dict[str, Any] | None = None,
    ) -> ModelResult:
        """Handle zero-attempt preflight validation errors."""
        end_mono = self.clock.monotonic()
        end_utc = self.clock.now_utc()
        latency = (end_mono - start_mono) * 1000.0

        audit_record = LogicalCallAuditRecord(
            call_id=call.call_id,
            operation_type=call.operation_type,
            requested_model=call.model_identifier,
            requested_digest=call.model_digest,
            prompt_version=call.prompt_version,
            system_prompt_version=call.system_prompt_version,
            schema_id=schema.schema_id if schema else None,
            schema_version=schema.version if schema else None,
            effective_settings=effective_settings or {},
            context_limit=call.context_limit,
            input_fingerprint=call.input_fingerprint,
            start_time_utc=start_utc,
            end_time_utc=end_utc,
            latency_ms=latency,
            outcome=str(error.category),
            error_code=error.details.get("reason") if error.details else None,
            attempts_count=len(attempts),
            attempts=attempts,
        )
        self.audit_manager.record(audit_record)

        return ModelResult(
            call_id=call.call_id,
            model_identifier=call.model_identifier,
            output_text=None,
            parsed_output=None,
            error=error,
            latency_ms=latency,
            token_usage=None,
        )

