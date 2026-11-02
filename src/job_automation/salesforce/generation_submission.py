"""Salesforce Generation Request submission, active reuse, idempotent replay, and offline feedback (SF-06).

Implements the candidate submission workflow matching JA_GenerationSubmit invocable Apex action,
enforcing parent job locking, catalog template validation, active duplicate reuse, immutable replay
receipts, and explicit unavailable-job consent gating.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import re
import uuid
from typing import Any

from job_automation.contracts.enums import ContextStrategy, DocumentType, GenerationProcessing
from job_automation.generation.request_mapping import (
    MAX_CLIENT_KEY_LENGTH,
    MAX_TEMPLATE_ID_LENGTH,
    canonicalize_salesforce_id,
)

UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


class SubmissionOutcome(str, Enum):
    """Outcomes from submitting a generation request."""

    CREATED = "created"
    REUSED_ACTIVE = "reused_active"
    REPLAYED = "replayed"
    CONFIRMATION_REQUIRED = "confirmation_required"
    REJECTED = "rejected"
    RETRYABLE_CONFLICT = "retryable_conflict"


@dataclass(frozen=True)
class GenerationOptionCatalogEntry:
    """Entry in the generation options catalog matching JA_Generation_Option__mdt."""

    template_id: str
    document_type: str
    allowed_languages: tuple[str, ...]
    is_enabled: bool = True
    catalog_version: str = "1.0.0"
    sort_order: int = 1


DEFAULT_CATALOG: dict[str, GenerationOptionCatalogEntry] = {
    "layout-cv-basic-a4": GenerationOptionCatalogEntry(
        template_id="layout-cv-basic-a4",
        document_type="cv",
        allowed_languages=("de", "en"),
        is_enabled=True,
        catalog_version="1.0.0",
        sort_order=1,
    ),
    "layout-cv-compact-a4": GenerationOptionCatalogEntry(
        template_id="layout-cv-compact-a4",
        document_type="cv",
        allowed_languages=("de", "en"),
        is_enabled=True,
        catalog_version="1.0.0",
        sort_order=2,
    ),
    "layout-letter-basic-a4": GenerationOptionCatalogEntry(
        template_id="layout-letter-basic-a4",
        document_type="cover_letter",
        allowed_languages=("de", "en"),
        is_enabled=True,
        catalog_version="1.0.0",
        sort_order=1,
    ),
    "layout-letter-compact-a4": GenerationOptionCatalogEntry(
        template_id="layout-letter-compact-a4",
        document_type="cover_letter",
        allowed_languages=("de", "en"),
        is_enabled=True,
        catalog_version="1.0.0",
        sort_order=2,
    ),
}


@dataclass(frozen=True)
class SubmissionIntent:
    """User intent parameters for document generation."""

    job_id: str
    document_type: str
    template_id: str
    submission_token: str
    language: str = "de"
    context_strategy: str = "json"
    allow_unavailable_job: bool = False
    creation_mode: str = "reuse_or_create"
    predecessor_request_id: str | None = None
    user_id: str = "005000000000001AAA"
    catalog_version: str = "1.0.0"

    @property
    def submission_key(self) -> str:
        """Deterministic unique submission key scoped by user and client token."""
        return f"{self.user_id}:{self.submission_token.strip()}"

    def to_canonical_payload(self) -> str:
        """Deterministic canonical JSON serialization for exact replay equality comparison."""
        doc_type = self.document_type.strip().lower()
        lang = self.language.strip().lower()
        strat = self.context_strategy.strip().lower()
        mode = self.creation_mode.strip().lower()

        data: dict[str, Any] = {
            "allowUnavailableJob": bool(self.allow_unavailable_job),
            "contextStrategy": strat,
            "creationMode": mode,
            "documentType": doc_type,
            "jobId": self.job_id.strip(),
            "language": lang,
            "predecessorRequestId": self.predecessor_request_id.strip() if self.predecessor_request_id else None,
            "templateId": self.template_id.strip(),
        }
        return json.dumps(data, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class SubmissionResult:
    """Outcome and feedback from submitting a generation request."""

    outcome: SubmissionOutcome
    is_success: bool
    message: str
    request_id: str | None = None
    request_name: str | None = None
    processing_state: str | None = None
    record_url: str | None = None


@dataclass
class SimulatedJobRecord:
    """Simulated Salesforce Job__c record."""

    id: str
    name: str
    job_title: str
    canonical_job_id: str
    availability: str = "Active"
    is_deleted: bool = False


@dataclass
class SimulatedGenerationRequest:
    """Simulated Salesforce Generation_Request__c record."""

    id: str
    name: str
    job_id: str
    document_type: str
    language: str
    template_id: str
    context_strategy: str
    allow_unavailable_job: bool
    status: str
    created_by_id: str
    created_date: datetime
    predecessor_request_id: str | None = None
    client_request_key: str | None = None
    contract_schema_version: str = "1.0"
    completed_at: datetime | None = None
    error_reason: str | None = None
    error_message: str | None = None
    result_artifact_ref: str | None = None


@dataclass
class SimulatedSubmissionReceipt:
    """Simulated Salesforce JA_Generation_Submission__c record."""

    id: str
    submission_key: str
    payload_version: str
    intent_payload: str
    request_id: str
    outcome: str
    created_date: datetime


class GenerationSubmissionService:
    """Transactional generation submission engine modeling Salesforce Apex & Flow behavior (SF-06)."""

    def __init__(
        self,
        catalog: dict[str, GenerationOptionCatalogEntry] | None = None,
    ) -> None:
        self.catalog = dict(catalog or DEFAULT_CATALOG)
        self.jobs: dict[str, SimulatedJobRecord] = {}
        self.requests: dict[str, SimulatedGenerationRequest] = {}
        self.receipts: dict[str, SimulatedSubmissionReceipt] = {}
        self._next_request_number = 1
        self._next_receipt_number = 1
        self._simulate_lock_contention = False
        self._simulate_receipt_failure = False

    def get_request(self, request_id: str) -> SimulatedGenerationRequest | None:
        canon = canonicalize_salesforce_id(request_id)
        for rid, req in self.requests.items():
            if canonicalize_salesforce_id(rid) == canon:
                return req
        return None

    def get_job(self, job_id: str) -> SimulatedJobRecord | None:
        canon = canonicalize_salesforce_id(job_id)
        for jid, job in self.jobs.items():
            if canonicalize_salesforce_id(jid) == canon:
                return job
        return None

    def transition_status(
        self,
        request_id: str,
        new_status: str,
        error_reason: str | None = None,
        error_message: str | None = None,
    ) -> None:
        req = self.get_request(request_id)
        if req:
            req.status = new_status
            if error_reason:
                req.error_reason = error_reason
            if error_message:
                req.error_message = error_message

    def register_job(
        self,
        job_id: str,
        name: str,
        job_title: str,
        canonical_job_id: str,
        availability: str = "Active",
    ) -> SimulatedJobRecord:
        """Register a Job__c record in the simulation."""
        rec = SimulatedJobRecord(
            id=job_id,
            name=name,
            job_title=job_title,
            canonical_job_id=canonical_job_id,
            availability=availability,
        )
        self.jobs[job_id] = rec
        return rec

    def submit(self, intent: SubmissionIntent) -> SubmissionResult:
        """Execute atomic submission with parent locking, duplicate reuse, and replay verification."""
        # 1. Parameter Validation
        if not intent.job_id or not intent.job_id.strip():
            return SubmissionResult(
                outcome=SubmissionOutcome.REJECTED,
                is_success=False,
                message="Target Job ID is required.",
            )

        if not intent.submission_token or not intent.submission_token.strip():
            return SubmissionResult(
                outcome=SubmissionOutcome.REJECTED,
                is_success=False,
                message="Submission token is required for idempotent submission.",
            )

        doc_type = intent.document_type.strip().lower()
        if doc_type not in ("cv", "cover_letter"):
            return SubmissionResult(
                outcome=SubmissionOutcome.REJECTED,
                is_success=False,
                message="Invalid document type: must be cv or cover_letter.",
            )

        lang = intent.language.strip().lower() if intent.language else "de"
        if lang not in ("de", "en"):
            return SubmissionResult(
                outcome=SubmissionOutcome.REJECTED,
                is_success=False,
                message="Invalid language: must be de or en.",
            )

        strat = intent.context_strategy.strip().lower() if intent.context_strategy else "json"
        if strat not in ("json", "rag"):
            return SubmissionResult(
                outcome=SubmissionOutcome.REJECTED,
                is_success=False,
                message="Invalid context strategy: must be json or rag.",
            )

        tmpl = intent.template_id.strip() if intent.template_id else ""
        if not tmpl:
            return SubmissionResult(
                outcome=SubmissionOutcome.REJECTED,
                is_success=False,
                message="Template ID is required.",
            )

        if len(tmpl) > MAX_TEMPLATE_ID_LENGTH:
            return SubmissionResult(
                outcome=SubmissionOutcome.REJECTED,
                is_success=False,
                message=f"Template ID exceeds maximum length of {MAX_TEMPLATE_ID_LENGTH}.",
            )

        mode = intent.creation_mode.strip().lower() if intent.creation_mode else "reuse_or_create"
        if mode not in ("reuse_or_create", "regenerate"):
            return SubmissionResult(
                outcome=SubmissionOutcome.REJECTED,
                is_success=False,
                message="Invalid creation mode: must be reuse_or_create or regenerate.",
            )

        # 2. Template Catalog Validation
        if tmpl not in self.catalog:
            return SubmissionResult(
                outcome=SubmissionOutcome.REJECTED,
                is_success=False,
                message=f"Unknown template ID: {tmpl}. Please select a valid template from the catalog.",
            )

        cat_entry = self.catalog[tmpl]
        if not cat_entry.is_enabled:
            return SubmissionResult(
                outcome=SubmissionOutcome.REJECTED,
                is_success=False,
                message=f"Template {tmpl} is currently disabled.",
            )

        if cat_entry.document_type != doc_type:
            return SubmissionResult(
                outcome=SubmissionOutcome.REJECTED,
                is_success=False,
                message=f"Template {tmpl} does not support document type {doc_type}.",
            )

        if lang not in cat_entry.allowed_languages:
            return SubmissionResult(
                outcome=SubmissionOutcome.REJECTED,
                is_success=False,
                message=f"Template {tmpl} does not support language {lang}.",
            )

        # 3. Replay Check via JA_Generation_Submission__c
        sub_key = intent.submission_key
        canonical_payload = intent.to_canonical_payload()

        if sub_key in self.receipts:
            existing_receipt = self.receipts[sub_key]
            if existing_receipt.intent_payload == canonical_payload:
                # Exact replay: return saved request even if its state transitioned
                linked_req = self.requests.get(existing_receipt.request_id)
                if linked_req is not None:
                    return SubmissionResult(
                        outcome=SubmissionOutcome.REPLAYED,
                        is_success=True,
                        request_id=linked_req.id,
                        request_name=linked_req.name,
                        processing_state=linked_req.status,
                        record_url=f"/{linked_req.id}",
                        message=f"Request {linked_req.name} was previously submitted. Current state: {linked_req.status}.",
                    )
            else:
                # Conflict: same token with different parameters
                return SubmissionResult(
                    outcome=SubmissionOutcome.REJECTED,
                    is_success=False,
                    message="Submission token conflict: this token was previously used with different parameters.",
                )

        # 4. Concurrency Contention Check
        if self._simulate_lock_contention:
            return SubmissionResult(
                outcome=SubmissionOutcome.RETRYABLE_CONFLICT,
                is_success=False,
                message="Concurrency contention detected while locking records. Please retry submission.",
            )

        # 5. Parent Job Validation & Row Lock
        job = self.jobs.get(intent.job_id)
        if job is None or job.is_deleted:
            return SubmissionResult(
                outcome=SubmissionOutcome.REJECTED,
                is_success=False,
                message="Target Job record not found or inaccessible.",
            )

        if not job.canonical_job_id or not UUID_PATTERN.match(job.canonical_job_id.strip()):
            return SubmissionResult(
                outcome=SubmissionOutcome.REJECTED,
                is_success=False,
                message="Target Job record lacks a valid Canonical Job ID.",
            )

        # 6. Availability and Failure History Invariants
        is_unavail = (job.availability or "").strip().lower() == "unavailable"
        if is_unavail and not intent.allow_unavailable_job:
            return SubmissionResult(
                outcome=SubmissionOutcome.CONFIRMATION_REQUIRED,
                is_success=False,
                message="This job is marked as Unavailable. Explicit consent is required to generate documents for unavailable jobs.",
            )

        # Check prior failed requests for job_unavailable
        unavail_failures = [
            r for r in self.requests.values()
            if r.job_id == intent.job_id
            and r.document_type == doc_type
            and (r.status or "").strip().lower() == "failed"
            and r.error_reason == "job_unavailable"
            and r.created_by_id == intent.user_id
        ]
        if unavail_failures and not intent.allow_unavailable_job:
            failed_req = unavail_failures[0]
            return SubmissionResult(
                outcome=SubmissionOutcome.CONFIRMATION_REQUIRED,
                is_success=False,
                request_id=failed_req.id,
                request_name=failed_req.name,
                processing_state=failed_req.status,
                record_url=f"/{failed_req.id}",
                message=f"A previous request ({failed_req.name}) failed because this job was unavailable. Explicit override consent is required to retry.",
            )

        # 7. Branch: Ordinary Mode (reuse_or_create)
        if mode == "reuse_or_create":
            # Search active requests for this candidate, job, and document type
            active_states = {"pending", "running", "upload_pending"}
            active_matches = [
                r for r in self.requests.values()
                if r.job_id == intent.job_id
                and r.document_type == doc_type
                and (r.status or "").strip().lower() in active_states
                and r.created_by_id == intent.user_id
                and r.language == lang
                and r.template_id == tmpl
                and r.context_strategy == strat
                and r.allow_unavailable_job == bool(intent.allow_unavailable_job)
            ]

            if active_matches:
                # Deterministic selection: oldest by created_date, then id
                active_matches.sort(key=lambda x: (x.created_date, x.id))
                matched_req = active_matches[0]

                # Insert receipt linking submission token to existing active request
                receipt_id = f"a03{self._next_receipt_number:012d}"
                self._next_receipt_number += 1
                self.receipts[sub_key] = SimulatedSubmissionReceipt(
                    id=receipt_id,
                    submission_key=sub_key,
                    payload_version="1.0",
                    intent_payload=canonical_payload,
                    request_id=matched_req.id,
                    outcome=SubmissionOutcome.REUSED_ACTIVE.value,
                    created_date=datetime.now(timezone.utc),
                )

                return SubmissionResult(
                    outcome=SubmissionOutcome.REUSED_ACTIVE,
                    is_success=True,
                    request_id=matched_req.id,
                    request_name=matched_req.name,
                    processing_state=matched_req.status,
                    record_url=f"/{matched_req.id}",
                    message=f"An identical active request already exists: {matched_req.name} ({matched_req.status}). No additional request was created.",
                )

            # Check if matching terminal history exists
            terminal_states = {"ready_for_review", "failed"}
            terminal_matches = [
                r for r in self.requests.values()
                if r.job_id == intent.job_id
                and r.document_type == doc_type
                and (r.status or "").strip().lower() in terminal_states
                and r.created_by_id == intent.user_id
                and r.language == lang
                and r.template_id == tmpl
                and r.context_strategy == strat
            ]

            if terminal_matches:
                terminal_matches.sort(key=lambda x: x.created_date, reverse=True)
                term = terminal_matches[0]
                return SubmissionResult(
                    outcome=SubmissionOutcome.CONFIRMATION_REQUIRED,
                    is_success=False,
                    request_id=term.id,
                    request_name=term.name,
                    processing_state=term.status,
                    record_url=f"/{term.id}",
                    message=f"A previous request ({term.name} - {term.status}) exists with identical options. Confirm deliberate regeneration to generate another draft.",
                )

            # Insert fresh Pending request
            now = datetime.now(timezone.utc)
            req_id = f"a02{self._next_request_number:012d}"
            req_name = f"GR-{self._next_request_number:06d}"
            self._next_request_number += 1

            new_req = SimulatedGenerationRequest(
                id=req_id,
                name=req_name,
                job_id=intent.job_id,
                document_type=doc_type,
                language=lang,
                template_id=tmpl,
                context_strategy=strat,
                allow_unavailable_job=bool(intent.allow_unavailable_job),
                status="Pending",
                created_by_id=intent.user_id,
                created_date=now,
                contract_schema_version="1.0",
                client_request_key=None,
            )

            # Simulate compound atomic transaction
            if self._simulate_receipt_failure:
                # Receipt insert fails -> compound rollback, request is NOT persisted
                return SubmissionResult(
                    outcome=SubmissionOutcome.REJECTED,
                    is_success=False,
                    message="Failed to commit submission receipt; compound transaction rolled back.",
                )

            self.requests[req_id] = new_req

            receipt_id = f"a03{self._next_receipt_number:012d}"
            self._next_receipt_number += 1
            self.receipts[sub_key] = SimulatedSubmissionReceipt(
                id=receipt_id,
                submission_key=sub_key,
                payload_version="1.0",
                intent_payload=canonical_payload,
                request_id=new_req.id,
                outcome=SubmissionOutcome.CREATED.value,
                created_date=now,
            )

            doc_label = "CV" if doc_type == "cv" else "Cover letter"
            return SubmissionResult(
                outcome=SubmissionOutcome.CREATED,
                is_success=True,
                request_id=new_req.id,
                request_name=new_req.name,
                processing_state=new_req.status,
                record_url=f"/{new_req.id}",
                message=f"{doc_label} request {new_req.name} queued. It will be processed when the local worker runs. You can close this window.",
            )

        # 8. Branch: Deliberate Regeneration (regenerate)
        if mode == "regenerate":
            if not intent.predecessor_request_id:
                return SubmissionResult(
                    outcome=SubmissionOutcome.REJECTED,
                    is_success=False,
                    message="Predecessor request ID is required for deliberate regeneration.",
                )

            pred = self.get_request(intent.predecessor_request_id)
            if pred is None:
                return SubmissionResult(
                    outcome=SubmissionOutcome.REJECTED,
                    is_success=False,
                    message="Predecessor request not found or inaccessible.",
                )

            if canonicalize_salesforce_id(pred.job_id) != canonicalize_salesforce_id(intent.job_id):
                return SubmissionResult(
                    outcome=SubmissionOutcome.REJECTED,
                    is_success=False,
                    message="Predecessor request belongs to a different Job.",
                )

            if pred.document_type != doc_type:
                return SubmissionResult(
                    outcome=SubmissionOutcome.REJECTED,
                    is_success=False,
                    message="Predecessor request document type does not match.",
                )

            if pred.error_reason == "job_unavailable" and not intent.allow_unavailable_job:
                return SubmissionResult(
                    outcome=SubmissionOutcome.CONFIRMATION_REQUIRED,
                    is_success=False,
                    request_id=pred.id,
                    request_name=pred.name,
                    processing_state=pred.status,
                    message="The predecessor request failed because this job was unavailable. Explicit override consent is required.",
                )

            now = datetime.now(timezone.utc)
            req_id = f"a02{self._next_request_number:012d}"
            req_name = f"GR-{self._next_request_number:06d}"
            self._next_request_number += 1

            new_req = SimulatedGenerationRequest(
                id=req_id,
                name=req_name,
                job_id=intent.job_id,
                predecessor_request_id=pred.id,
                document_type=doc_type,
                language=lang,
                template_id=tmpl,
                context_strategy=strat,
                allow_unavailable_job=bool(intent.allow_unavailable_job),
                status="Pending",
                created_by_id=intent.user_id,
                created_date=now,
                contract_schema_version="1.0",
                client_request_key=None,
            )

            if self._simulate_receipt_failure:
                return SubmissionResult(
                    outcome=SubmissionOutcome.REJECTED,
                    is_success=False,
                    message="Failed to commit submission receipt; compound transaction rolled back.",
                )

            self.requests[req_id] = new_req

            receipt_id = f"a03{self._next_receipt_number:012d}"
            self._next_receipt_number += 1
            self.receipts[sub_key] = SimulatedSubmissionReceipt(
                id=receipt_id,
                submission_key=sub_key,
                payload_version="1.0",
                intent_payload=canonical_payload,
                request_id=new_req.id,
                outcome=SubmissionOutcome.CREATED.value,
                created_date=now,
            )

            doc_label = "CV" if doc_type == "cv" else "Cover letter"
            return SubmissionResult(
                outcome=SubmissionOutcome.CREATED,
                is_success=True,
                request_id=new_req.id,
                request_name=new_req.name,
                processing_state=new_req.status,
                record_url=f"/{new_req.id}",
                message=f"{doc_label} draft {new_req.name} queued as deliberate regeneration from {pred.name}. It will be processed when the local worker runs.",
            )

        return SubmissionResult(
            outcome=SubmissionOutcome.REJECTED,
            is_success=False,
            message="Unrecognized submission state.",
        )
