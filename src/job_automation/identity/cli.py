"""CLI subcommands for identity review and merge management."""

from __future__ import annotations

import argparse
import sys
import uuid

from job_automation.configuration import load_config
from job_automation.identity.service import IdentityService
from job_automation.storage.engine import StorageEngine


def register_identity_subparsers(subparsers: argparse._SubParsersAction) -> None:
    """Register identity review and merge subcommands."""
    identity_parser = subparsers.add_parser(
        "identity",
        help="Company/job identity review and merge operations",
    )
    id_sub = identity_parser.add_subparsers(dest="identity_command", required=True)

    # -------------------------------------------------------------------------
    # identity review ...
    # -------------------------------------------------------------------------
    review_parser = id_sub.add_parser("review", help="Manage identity review cases")
    review_sub = review_parser.add_subparsers(dest="review_command", required=True)

    # review list
    list_p = review_sub.add_parser("list", help="List identity review cases")
    list_p.add_argument("--status", choices=["pending", "accepted", "rejected", "deferred"], default=None)
    list_p.add_argument("--config", help="Path to app.json configuration")
    list_p.add_argument("--data-root", help="Override data root directory")

    # review show
    show_p = review_sub.add_parser("show", help="Show details of a review case")
    show_p.add_argument("--case-id", required=True, help="Review case ID")
    show_p.add_argument("--config", help="Path to app.json configuration")
    show_p.add_argument("--data-root", help="Override data root directory")

    # review decide
    decide_p = review_sub.add_parser("decide", help="Record decision on a review case")
    decide_p.add_argument("--case-id", required=True, help="Review case ID")
    decide_p.add_argument("--decision", choices=["accept", "reject", "defer"], required=True)
    decide_p.add_argument("--actor", required=True, help="Reviewer username or ID")
    decide_p.add_argument("--reason", required=True, help="Rationale for the decision")
    decide_p.add_argument("--config", help="Path to app.json configuration")
    decide_p.add_argument("--data-root", help="Override data root directory")

    # -------------------------------------------------------------------------
    # identity merge
    # -------------------------------------------------------------------------
    merge_p = id_sub.add_parser("merge", help="Merge two canonical jobs")
    merge_p.add_argument("--surviving-id", required=True, help="Surviving canonical job UUID")
    merge_p.add_argument("--merged-id", required=True, help="Predecessor canonical job UUID to merge")
    merge_p.add_argument("--actor", required=True, help="Actor executing the merge")
    merge_p.add_argument("--reason", required=True, help="Reason/evidence for merge")
    merge_p.add_argument("--config", help="Path to app.json configuration")
    merge_p.add_argument("--data-root", help="Override data root directory")

    # -------------------------------------------------------------------------
    # identity reverse-merge
    # -------------------------------------------------------------------------
    rev_p = id_sub.add_parser("reverse-merge", help="Reverse a prior canonical job merge")
    rev_p.add_argument("--operation-id", required=True, help="Operation ID of the merge to reverse")
    rev_p.add_argument("--actor", required=True, help="Actor executing the reversal")
    rev_p.add_argument("--reason", required=True, help="Reason for reversal")
    rev_p.add_argument("--config", help="Path to app.json configuration")
    rev_p.add_argument("--data-root", help="Override data root directory")


def run_identity_command(args: argparse.Namespace) -> int:
    """Dispatch identity CLI commands."""
    try:
        config, paths = load_config(
            config_path=getattr(args, "config", None),
            data_root_override=getattr(args, "data_root", None),
        )
        engine = StorageEngine.from_config(config, paths)
        service = IdentityService(engine)

        try:
            if args.identity_command == "review":
                if args.review_command == "list":
                    cases = service.list_review_cases(status=args.status)
                    print(f"Identity review cases ({len(cases)} found):")
                    for c in cases:
                        print(
                            f"  Case ID:  {c.case_id}\n"
                            f"    Status: {c.status}\n"
                            f"    Reason: {c.reason}\n"
                            f"    Source: {c.source_key.provider}/{c.source_key.board_id}/{c.source_key.source_posting_id}\n"
                            f"    Candidates: {[str(cid) for cid in c.candidate_job_ids]}"
                        )
                    return 0

                elif args.review_command == "show":
                    case = engine.identity.get_review_case(args.case_id)
                    if not case:
                        print(f"Error: Review case '{args.case_id}' not found", file=sys.stderr)
                        return 1
                    print(f"Review Case: {case['case_id']}")
                    print(f"  Status:    {case['status']}")
                    print(f"  Reason:    {case['reason']}")
                    print(f"  Source:    {case['source_key']}")
                    print(f"  Candidates:{case['candidate_job_ids']}")
                    print(f"  Evidence:  {case['evidence']}")
                    if case.get("decision_actor"):
                        print(f"  Decided:   {case['decided_at']} by {case['decision_actor']}: {case['decision_reason']}")
                    return 0

                elif args.review_command == "decide":
                    updated = service.decide_review_case(
                        case_id=args.case_id,
                        decision=args.decision,
                        actor=args.actor,
                        reason=args.reason,
                    )
                    print(f"Review case {updated.case_id} updated: status={updated.status}")
                    return 0

            elif args.identity_command == "merge":
                surviving_uuid = uuid.UUID(args.surviving_id)
                merged_uuid = uuid.UUID(args.merged_id)
                op = service.merge_canonical_jobs(
                    surviving_id=surviving_uuid,
                    merged_id=merged_uuid,
                    actor=args.actor,
                    reason=args.reason,
                )
                print(f"Merge successful: operation_id={op.operation_id}")
                print(f"  Surviving Canonical: {op.surviving_canonical_id}")
                print(f"  Merged Canonical:    {op.merged_canonical_id}")
                return 0

            elif args.identity_command == "reverse-merge":
                op = service.reverse_merge(
                    operation_id=args.operation_id,
                    actor=args.actor,
                    reason=args.reason,
                )
                print(f"Reversal successful: operation_id={op.operation_id}")
                print(f"  Target Merge Op:     {op.target_merge_operation_id}")
                print(f"  Surviving Canonical: {op.surviving_canonical_id}")
                print(f"  Restored Canonical:  {op.restored_canonical_id}")
                return 0

            print(f"Unknown identity command: {args.identity_command}", file=sys.stderr)
            return 2

        finally:
            engine.close()

    except Exception as exc:
        print(f"Identity command FAILED: {exc}", file=sys.stderr)
        return 2

