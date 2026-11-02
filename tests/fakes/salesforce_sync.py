"""Stateful in-memory fake Salesforce Gateway for SYNC-01 testing (SYNC-01-S06, S07, S09).

Conforms to SalesforceGatewayV2 Protocol.
Tracks:
- In-memory sObject stores with External ID indexing
- Physical transmission counts vs logical upserts
- Scriptable simulated failures (transient errors, lost responses with committed state, permission issues)
- Direct candidate field mutations to test candidate-owned field preservation
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Callable

from job_automation.contracts.errors import ClassifiedError, ErrorCategory
from job_automation.contracts.interfaces import SalesforceGatewayV2
from job_automation.contracts.salesforce import (
    AttemptSummary,
    ConnectionCheckRequest,
    ConnectionCheckResult,
    DescribeObjectRequest,
    DescribeObjectResult,
    GatewayFailure,
    GatewayResult,
    GetRecordRequest,
    GetRecordResult,
    LimitsRequest,
    LimitsResult,
    OperationKind,
    QueryPageRequest,
    QueryPageResult,
    RecoveryAction,
    RemoteOutcome,
    UpdateRequest,
    UpdateResult,
    UpsertRequest,
    UpsertResult,
)


class FakeSalesforceGatewayV2(SalesforceGatewayV2):
    """Stateful fake gateway implementing SalesforceGatewayV2 for sync testing."""

    def __init__(self, org_id: str = "00D000000000001") -> None:
        self.org_id = org_id
        # records[object_name][record_id] = fields dict
        self.records: dict[str, dict[str, dict[str, Any]]] = {}
        # external_ids[object_name][external_id_value] = record_id
        self.external_ids: dict[str, dict[str, str]] = {}

        # Tracking counters and request log
        self.physical_upsert_count: int = 0
        self.physical_get_record_count: int = 0
        self.physical_query_count: int = 0
        self.upsert_requests: list[UpsertRequest] = []

        # Scriptable hooks / overrides
        self._next_upsert_failure: GatewayFailure | None = None
        self._next_upsert_hook: Callable[[UpsertRequest], GatewayResult[UpsertResult] | None] | None = None
        self._simulate_lost_response_on_upsert: bool = False

    def simulate_candidate_edit(
        self,
        object_name: str,
        record_id: str,
        updates: dict[str, Any],
    ) -> None:
        """Simulate candidate editing candidate-owned fields directly in Salesforce."""
        if object_name in self.records and record_id in self.records[object_name]:
            self.records[object_name][record_id].update(updates)
            self.records[object_name][record_id]["SystemModstamp"] = uuid.uuid4().hex

    def check_connection(
        self, request: ConnectionCheckRequest
    ) -> GatewayResult[ConnectionCheckResult]:
        return GatewayResult(
            value=ConnectionCheckResult(
                org_id=self.org_id,
                user_id="005000000000001",
                username="test@example.com",
                instance_url="https://example.my.salesforce.com",
            )
        )

    def get_limits(self, request: LimitsRequest) -> GatewayResult[LimitsResult]:
        return GatewayResult(
            value=LimitsResult(
                daily_api_requests_max=15000,
                daily_api_requests_remaining=14900,
            )
        )

    def describe_object(
        self, request: DescribeObjectRequest
    ) -> GatewayResult[DescribeObjectResult]:
        return GatewayResult(
            value=DescribeObjectResult(
                object_name=request.object_name,
                is_createable=True,
                is_updateable=True,
                is_queryable=True,
                is_custom=True,
            )
        )

    def get_record(self, request: GetRecordRequest) -> GatewayResult[GetRecordResult]:
        self.physical_get_record_count += 1
        obj = request.object_name
        self.records.setdefault(obj, {})
        self.external_ids.setdefault(obj, {})

        rec_id: str | None = request.record_id
        if not rec_id and request.external_id_field and request.external_id_value:
            rec_id = self.external_ids[obj].get(request.external_id_value)

        if not rec_id or rec_id not in self.records[obj]:
            fail = GatewayFailure(
                error=ClassifiedError.not_found(
                    f"Record not found for object '{obj}' with identifier '{request.record_id or request.external_id_value}'"
                ),
                http_status=404,
                operation_kind=OperationKind.GET_RECORD,
                remote_outcome=RemoteOutcome.NOT_SENT,
                recovery_action=RecoveryAction.FIX_CONFIGURATION,
            )
            return GatewayResult(failure=fail)

        all_fields = self.records[obj][rec_id]
        if request.fields:
            filtered = {k: all_fields.get(k) for k in request.fields}
            filtered["Id"] = rec_id
        else:
            filtered = copy.deepcopy(all_fields)

        return GatewayResult(
            value=GetRecordResult(
                object_name=obj,
                record_id=rec_id,
                fields=filtered,
            )
        )

    def query_page(self, request: QueryPageRequest) -> GatewayResult[QueryPageResult]:
        self.physical_query_count += 1
        # Extract target object from simple SOQL: SELECT ... FROM Object__c
        tokens = request.soql.split()
        try:
            from_idx = tokens.index("FROM")
            obj = tokens[from_idx + 1]
        except (ValueError, IndexError):
            obj = "Job__c"

        self.records.setdefault(obj, {})
        all_rows = sorted(list(self.records[obj].values()), key=lambda r: str(r.get("Id", "")))

        # Handle keyset filter: WHERE Id > '...'
        soql = request.soql
        if "WHERE Id > '" in soql:
            after_id = soql.split("WHERE Id > '")[1].split("'")[0]
            all_rows = [r for r in all_rows if str(r.get("Id", "")) > after_id]

        limit = None
        if " LIMIT " in soql:
            try:
                limit_str = soql.split(" LIMIT ")[1].split()[0]
                limit = int(limit_str)
            except (ValueError, IndexError):
                limit = None

        if limit is not None:
            page_rows = all_rows[:limit]
        else:
            page_rows = all_rows

        return GatewayResult(
            value=QueryPageResult(
                total_size=len(self.records[obj]),
                done=len(page_rows) == len(all_rows),
                records=copy.deepcopy(page_rows),
            )
        )

    def upsert_by_external_id(
        self, request: UpsertRequest
    ) -> GatewayResult[UpsertResult]:
        self.physical_upsert_count += 1
        self.upsert_requests.append(copy.deepcopy(request))

        # Check programmed failure hook
        if self._next_upsert_hook is not None:
            hook = self._next_upsert_hook
            self._next_upsert_hook = None
            res = hook(request)
            if res is not None:
                return res

        if self._next_upsert_failure is not None:
            fail = self._next_upsert_failure
            self._next_upsert_failure = None
            return GatewayResult(failure=fail)

        obj = request.object_name
        self.records.setdefault(obj, {})
        self.external_ids.setdefault(obj, {})

        ext_val = request.external_id_value
        existing_id = self.external_ids[obj].get(ext_val)

        if existing_id is not None:
            rec_id = existing_id
            created = False
            # Update fields
            self.records[obj][rec_id].update(request.fields)
            self.records[obj][rec_id]["SystemModstamp"] = uuid.uuid4().hex
        else:
            rec_id = f"a00{uuid.uuid4().hex[:15]}"
            created = True
            new_record = copy.deepcopy(request.fields)
            new_record["Id"] = rec_id
            new_record[request.external_id_field] = ext_val
            new_record["SystemModstamp"] = uuid.uuid4().hex
            # Set candidate defaults for new records if not present
            if obj == "Job__c":
                new_record.setdefault("Application_Progress__c", "New")
                new_record.setdefault("Candidate_Notes__c", None)
                new_record.setdefault("Candidate_Decision__c", None)
                new_record.setdefault("Follow_Up_Date__c", None)
                new_record.setdefault("Interview_Date__c", None)

            self.records[obj][rec_id] = new_record
            self.external_ids[obj][ext_val] = rec_id

        # Lost response simulation: the record was committed to Salesforce state,
        # but the client received an unknown timeout / connection error!
        if self._simulate_lost_response_on_upsert:
            self._simulate_lost_response_on_upsert = False
            fail = GatewayFailure(
                error=ClassifiedError.transient_network(
                    "Connection reset by peer after write commit (lost response)"
                ),
                http_status=None,
                operation_kind=OperationKind.UPSERT_BY_EXTERNAL_ID,
                remote_outcome=RemoteOutcome.UNKNOWN,
                recovery_action=RecoveryAction.RECONCILE,
                attempts=[
                    AttemptSummary(
                        attempt_number=1,
                        purpose="upsert_by_external_id",
                        duration_ms=150.0,
                        uncertain_transmission=True,
                    )
                ],
            )
            return GatewayResult(failure=fail)

        from datetime import datetime, timezone
        return GatewayResult(
            value=UpsertResult(
                object_name=obj,
                external_id_field=request.external_id_field,
                external_id_value=ext_val,
                record_id=rec_id,
                created=created,
                acknowledged_at=datetime.now(timezone.utc),
            )
        )

    def update_record(self, request: UpdateRequest) -> GatewayResult[UpdateResult]:
        obj = request.object_name
        self.records.setdefault(obj, {})
        rec_id = request.record_id

        if rec_id not in self.records[obj]:
            return GatewayResult(
                failure=GatewayFailure(
                    error=ClassifiedError.not_found(f"Record {rec_id} not found"),
                    http_status=404,
                    operation_kind=OperationKind.UPDATE_RECORD,
                    remote_outcome=RemoteOutcome.NOT_SENT,
                )
            )

        self.records[obj][rec_id].update(request.fields)
        self.records[obj][rec_id]["SystemModstamp"] = uuid.uuid4().hex
        from datetime import datetime, timezone
        return GatewayResult(
            value=UpdateResult(
                object_name=obj,
                record_id=rec_id,
                acknowledged_at=datetime.now(timezone.utc),
            )
        )
