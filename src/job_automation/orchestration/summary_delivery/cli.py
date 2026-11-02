"""Command-line interface for AUTO-03 per-run summary delivery inspection and operations."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from pathlib import Path

from job_automation.configuration import load_config
from job_automation.orchestration.summary_delivery.records import DeliveryState
from job_automation.orchestration.summary_delivery.service import SummaryDeliveryService
from job_automation.orchestration.summary_delivery.settings import load_summary_delivery_settings
from job_automation.storage.engine import StorageEngine

logger = logging.getLogger(__name__)


def register_delivery_subparsers(subparsers: argparse._SubParsersAction) -> None:
    """Register 'delivery' command group into the root or ops CLI parser."""
    deliv_parser = subparsers.add_parser(
        "delivery",
        help="Per-run summary delivery inspection, drain, and reconciliation (AUTO-03)",
    )
    deliv_sub = deliv_parser.add_subparsers(dest="delivery_command", help="Delivery actions")

    # 1. delivery status
    stat_p = deliv_sub.add_parser("status", help="Show summary delivery configuration and queue counts")
    stat_p.add_argument("--config", type=str, default=None, help="Path to config JSON")
    stat_p.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    stat_p.add_argument("--json", action="store_true", help="Output results in JSON format")

    # 2. delivery show
    show_p = deliv_sub.add_parser("show", help="Display delivery details and attempts for a specific run UUID")
    show_p.add_argument("--run-id", type=str, required=True, help="UUID of the pipeline run")
    show_p.add_argument("--config", type=str, default=None, help="Path to config JSON")
    show_p.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    show_p.add_argument("--json", action="store_true", help="Output results in JSON format")

    # 3. delivery list
    list_p = deliv_sub.add_parser("list", help="List summary delivery records")
    list_p.add_argument(
        "--state",
        type=str,
        choices=[s.value for s in DeliveryState],
        default=None,
        help="Filter by delivery state",
    )
    list_p.add_argument("--limit", type=int, default=50, help="Maximum records to list (default 50)")
    list_p.add_argument("--config", type=str, default=None, help="Path to config JSON")
    list_p.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    list_p.add_argument("--json", action="store_true", help="Output results in JSON format")

    # 4. delivery drain
    drain_p = deliv_sub.add_parser("drain", help="Dispatch all currently due summary deliveries")
    drain_p.add_argument("--limit", type=int, default=50, help="Maximum records to process")
    drain_p.add_argument("--recipient", type=str, default=None, help="Override test recipient for notification checks")
    drain_p.add_argument("--config", type=str, default=None, help="Path to config JSON")
    drain_p.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    drain_p.add_argument("--json", action="store_true", help="Output results in JSON format")

    # 5. delivery reconcile
    rec_p = deliv_sub.add_parser("reconcile", help="Reconcile remote summary state for a specific run UUID")
    rec_p.add_argument("--run-id", type=str, required=True, help="UUID of the pipeline run")
    rec_p.add_argument("--config", type=str, default=None, help="Path to config JSON")
    rec_p.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    rec_p.add_argument("--json", action="store_true", help="Output results in JSON format")

    # 6. delivery retry
    retry_p = deliv_sub.add_parser("retry", help="Reset retry allowance for a blocked or exhausted delivery")
    retry_p.add_argument("--run-id", type=str, required=True, help="UUID of the pipeline run")
    retry_p.add_argument("--additional-attempts", type=int, default=3, help="Additional attempts allowance")
    retry_p.add_argument("--config", type=str, default=None, help="Path to config JSON")
    retry_p.add_argument("--data-root", type=str, default=None, help="Override path for runtime data root")
    retry_p.add_argument("--json", action="store_true", help="Output results in JSON format")


def handle_delivery_commands(args: argparse.Namespace) -> int:
    """Handle dispatched 'delivery' subcommands."""
    subcmd = getattr(args, "delivery_command", None)
    if not subcmd:
        print("Usage: job_automation delivery {status,show,list,drain,reconcile,retry} ...", file=sys.stderr)
        return 2

    config, paths = load_config(
        config_path=getattr(args, "config", None),
        data_root_override=getattr(args, "data_root", None),
    )

    settings = load_summary_delivery_settings(getattr(paths, "summary_delivery_settings_path", None))
    engine = StorageEngine.from_config(config, paths)
    service = SummaryDeliveryService(engine=engine, settings=settings)

    as_json = getattr(args, "json", False)

    try:
        if subcmd == "status":
            counts: dict[str, int] = {}
            for st in DeliveryState:
                items = engine.summary_deliveries.list_deliveries(state=st, limit=1000)
                counts[st.value] = len(items)

            live_auth_status = "PENDING (no test_recipient configured)"
            if settings.test_recipient:
                live_auth_status = f"AUTHORIZED for test_recipient: {settings.test_recipient}"

            payload = {
                "enabled": settings.enabled,
                "salesforce_org_id": settings.salesforce_org_id,
                "target_object": settings.target_object_name,
                "test_recipient": settings.test_recipient,
                "live_notification_status": live_auth_status,
                "queue_counts": counts,
            }
            if as_json:
                print(json.dumps(payload, indent=2))
            else:
                print("==================================================================")
                print("  AUTO-03 SUMMARY DELIVERY STATUS")
                print("==================================================================")
                print(f"  Enabled:             {'YES' if settings.enabled else 'NO (Disabled)'}")
                print(f"  Salesforce Org ID:   {settings.salesforce_org_id or 'none'}")
                print(f"  Target sObject:      {settings.target_object_name}")
                print(f"  Test Recipient:      {settings.test_recipient or 'none'}")
                print(f"  Live Verification:   {live_auth_status}")
                print("------------------------------------------------------------------")
                print("  QUEUE COUNTS")
                for k, v in counts.items():
                    print(f"    {k:<20} {v}")
            return 0

        elif subcmd == "show":
            run_uuid = uuid.UUID(args.run_id)
            delivery = engine.summary_deliveries.get_delivery_by_run_id(run_uuid)
            if not delivery:
                msg = f"No delivery found for run ID '{run_uuid}'"
                if as_json:
                    print(json.dumps({"error": msg}))
                else:
                    print(f"Error: {msg}", file=sys.stderr)
                return 1

            receipt = engine.summary_deliveries.get_receipt(run_uuid)
            attempts = engine.summary_deliveries.list_attempts(delivery.delivery_id)

            if as_json:
                d_dict = json.loads(delivery.model_dump_json())
                d_dict["attempts"] = [json.loads(a.model_dump_json()) for a in attempts]
                if receipt:
                    d_dict["receipt"] = json.loads(receipt.model_dump_json())
                print(json.dumps(d_dict, indent=2))
            else:
                print("==================================================================")
                print("  SUMMARY DELIVERY DETAILS")
                print("==================================================================")
                print(f"  Run ID:              {delivery.run_id}")
                print(f"  State:               {delivery.state.value.upper()}")
                print(f"  Revision:            {delivery.revision}")
                print(f"  Target Org:          {delivery.org_id}")
                print(f"  Remote Record ID:    {delivery.remote_record_id or 'none'}")
                print(f"  Notification State:  {delivery.notification_state.value.upper()}")
                print(f"  Notification Receipt:{delivery.notification_receipt_id or 'none'}")
                print(f"  Dispatch Attempts:   {delivery.dispatch_attempts}")
                print(f"  Reconcile Attempts:  {delivery.reconcile_attempts}")
                print(f"  Next Due:            {delivery.next_due_at.isoformat() if delivery.next_due_at else 'none'}")
                print(f"  Acknowledged At:     {delivery.acknowledged_at.isoformat() if delivery.acknowledged_at else 'none'}")
                if delivery.last_error_message:
                    print(f"  Last Error:          [{delivery.last_error_category or 'ERROR'}] {delivery.last_error_message}")
                print("------------------------------------------------------------------")
                print(f"  ATTEMPTS ({len(attempts)})")
                for att in attempts:
                    print(
                        f"    #{att.attempt_sequence:<3} {att.operation_kind:<15} [{att.status.upper()}] "
                        f"http={att.http_status or '-'} dur={att.duration_ms:.1f}ms "
                        f"outcome={att.remote_outcome or '-'}"
                    )
            return 0

        elif subcmd == "list":
            st_filter = DeliveryState(args.state) if args.state else None
            deliveries = engine.summary_deliveries.list_deliveries(state=st_filter, limit=args.limit)

            if as_json:
                res_list = [json.loads(d.model_dump_json()) for d in deliveries]
                print(json.dumps(res_list, indent=2))
            else:
                print(f"Summary Deliveries ({len(deliveries)} records):")
                print(f"  {'RUN ID':<38} {'REV':<5} {'STATE':<18} {'REMOTE ID':<20} {'NOTIFICATION':<12}")
                print("  " + "-" * 95)
                for d in deliveries:
                    print(
                        f"  {str(d.run_id):<38} {d.revision:<5} {d.state.value:<18} "
                        f"{(d.remote_record_id or 'none'):<20} {d.notification_state.value:<12}"
                    )
            return 0

        elif subcmd == "drain":
            reports = service.drain(limit=args.limit, test_recipient=args.recipient)
            if as_json:
                print(json.dumps([json.loads(r.model_dump_json()) for r in reports], indent=2))
            else:
                print(f"Drained {len(reports)} delivery records:")
                for r in reports:
                    print(
                        f"  Run {str(r.run_id)[:8]} -> state={r.delivery_state.value} "
                        f"remote={r.remote_record_id or 'none'} notif={r.notification_state.value}"
                    )
            return 0

        elif subcmd == "reconcile":
            run_uuid = uuid.UUID(args.run_id)
            report = service.reconcile_delivery(run_id=run_uuid)
            if as_json:
                print(report.model_dump_json(indent=2))
            else:
                print(
                    f"Reconciled run {run_uuid} -> state={report.delivery_state.value} "
                    f"remote={report.remote_record_id or 'none'} notif={report.notification_state.value}"
                )
            return 0

        elif subcmd == "retry":
            run_uuid = uuid.UUID(args.run_id)
            updated = service.reset_retry(run_id=run_uuid, additional_attempts=args.additional_attempts)
            if as_json:
                print(updated.model_dump_json(indent=2))
            else:
                print(f"Reset retry for run {run_uuid}: state={updated.state.value}, deadline={updated.retry_deadline.isoformat()}")
            return 0

        return 0

    except Exception as exc:
        logger.exception("Error executing delivery command '%s': %s", subcmd, exc)
        if as_json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1

