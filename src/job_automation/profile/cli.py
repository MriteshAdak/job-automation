"""CLI subcommand handlers for candidate profile management (PROFILE-01).

Provides safe command execution for:
- profile import
- profile review
- profile approve
- profile history
- profile show
- profile resolve
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from job_automation.configuration import load_config
from job_automation.profile.service import ProfileService
from job_automation.storage.engine import StorageEngine


def register_profile_subparsers(subparsers: argparse._SubParsersAction) -> None:
    """Register profile command group and its subcommands."""
    profile_parser = subparsers.add_parser(
        "profile",
        help="Candidate profile and evidence management",
    )
    profile_sub = profile_parser.add_subparsers(
        dest="profile_command",
        help="Profile actions",
    )

    # 1. import
    import_parser = profile_sub.add_parser("import", help="Import unapproved candidate facts draft")
    import_parser.add_argument("--input", required=True, type=str, help="Path to structured input JSON")
    import_parser.add_argument("--config", default=None, type=str, help="Path to app configuration JSON")
    import_parser.add_argument("--data-root", default=None, type=str, help="Override runtime data root")

    # 2. review
    review_parser = profile_sub.add_parser("review", help="Review an unapproved draft by ID")
    review_parser.add_argument("--draft-id", required=True, type=str, help="UUID of draft to review")
    review_parser.add_argument("--config", default=None, type=str, help="Path to app configuration JSON")
    review_parser.add_argument("--data-root", default=None, type=str, help="Override runtime data root")

    # 3. approve
    approve_parser = profile_sub.add_parser("approve", help="Explicitly approve a reviewed draft and publish snapshot")
    approve_parser.add_argument("--draft-id", required=True, type=str, help="UUID of draft being approved")
    approve_parser.add_argument("--digest", required=True, type=str, help="Expected draft content digest")
    approve_parser.add_argument("--approved-by", required=True, type=str, help="Candidate/approver identifier")
    approve_parser.add_argument("--notes", default=None, type=str, help="Approval notes or version summary")
    approve_parser.add_argument("--expected-base", default=None, type=str, help="Expected base version string")
    approve_parser.add_argument("--config", default=None, type=str, help="Path to app configuration JSON")
    approve_parser.add_argument("--data-root", default=None, type=str, help="Override runtime data root")

    # 4. history
    hist_parser = profile_sub.add_parser("history", help="List published profile version history")
    hist_parser.add_argument("--config", default=None, type=str, help="Path to app configuration JSON")
    hist_parser.add_argument("--data-root", default=None, type=str, help="Override runtime data root")

    # 5. show
    show_parser = profile_sub.add_parser("show", help="Display or export an approved profile snapshot")
    show_parser.add_argument("--version", default=None, type=str, help="Version string (default: current)")
    show_parser.add_argument("--export", default=None, type=str, help="Optional output path to export snapshot JSON")
    show_parser.add_argument("--config", default=None, type=str, help="Path to app configuration JSON")
    show_parser.add_argument("--data-root", default=None, type=str, help="Override runtime data root")

    # 6. resolve
    resolve_parser = profile_sub.add_parser("resolve", help="Resolve exact C08 candidate evidence citation")
    resolve_parser.add_argument("--version", required=True, type=str, help="Profile version cited")
    resolve_parser.add_argument("--fact-id", required=True, type=str, help="UUID of candidate fact cited")
    resolve_parser.add_argument("--config", default=None, type=str, help="Path to app configuration JSON")
    resolve_parser.add_argument("--data-root", default=None, type=str, help="Override runtime data root")


def handle_profile_commands(args: argparse.Namespace) -> int:
    """Dispatch profile subcommands."""
    cmd = args.profile_command
    if not cmd:
        print("Missing profile action. Run 'job_automation profile --help' for details.", file=sys.stderr)
        return 2

    try:
        config, paths = load_config(
            config_path=args.config,
            data_root_override=args.data_root,
        )
        engine = StorageEngine.from_config(config, paths)
        engine.migrate()  # ensure schema migrations are applied
        service = ProfileService.from_engine(engine)

        try:
            if cmd == "import":
                return _run_import(service, args)
            if cmd == "review":
                return _run_review(service, args)
            if cmd == "approve":
                return _run_approve(service, args)
            if cmd == "history":
                return _run_history(service, args)
            if cmd == "show":
                return _run_show(service, args)
            if cmd == "resolve":
                return _run_resolve(service, args)
            print(f"Unknown profile command '{cmd}'", file=sys.stderr)
            return 2
        finally:
            engine.close()

    except Exception as exc:
        print(f"Profile operation: FAILED\n  Error: {exc}", file=sys.stderr)
        return 2


def _run_import(service: ProfileService, args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"Input file not found: '{args.input}'", file=sys.stderr)
        return 2

    content = input_path.read_text(encoding="utf-8")
    draft = service.import_draft(content)

    print("Profile draft imported: SUCCESS")
    print(f"  Draft ID:        {draft.draft_id}")
    print(f"  Candidate ID:    {draft.candidate_id}")
    print(f"  Facts Count:     {len(draft.facts)}")
    print(f"  Content Digest:  {draft.content_digest}")
    print(f"  Base Version:    {draft.base_profile_version or 'None'}")
    print("  Status:          UNAPPROVED (Pending deliberate candidate review and approval)")
    return 0


def _run_review(service: ProfileService, args: argparse.Namespace) -> int:
    draft_id = uuid.UUID(args.draft_id)
    draft = service.get_draft(draft_id)

    print("Profile draft review:")
    print(f"  Draft ID:        {draft.draft_id}")
    print(f"  Candidate ID:    {draft.candidate_id}")
    print(f"  Base Version:    {draft.base_profile_version or 'None'}")
    print(f"  Content Digest:  {draft.content_digest}")
    print(f"  Facts Count:     {len(draft.facts)}")
    for f in draft.facts:
        print(f"    - [{f.kind.value}] {f.title} (ID: {f.fact_id})")
        if f.start_date:
            print(f"      Dates: {f.start_date.value} to {f.end_date.value if f.end_date else ('ongoing' if f.is_ongoing else 'unspecified')}")
        print(f"      Allowed Uses: {f.allowed_uses}")
    return 0


def _run_approve(service: ProfileService, args: argparse.Namespace) -> int:
    draft_id = uuid.UUID(args.draft_id)
    snapshot = service.approve_and_publish(
        draft_id=draft_id,
        expected_draft_digest=args.digest,
        approved_by=args.approved_by,
        notes=args.notes,
        expected_base_version=args.expected_base,
    )

    print("Profile publication: SUCCESS")
    print(f"  Profile Version: {snapshot.profile_version}")
    print(f"  Candidate ID:    {snapshot.candidate_id}")
    print(f"  Approved By:     {snapshot.approval_metadata.approved_by}")
    print(f"  Approved At:     {snapshot.approval_metadata.approved_at.isoformat()}")
    print(f"  Facts Count:     {len(snapshot.evidence_records)}")
    return 0


def _run_history(service: ProfileService, args: argparse.Namespace) -> int:
    records = service.list_history()
    print("Profile version history:")
    if not records:
        print("  No published profile versions found.")
        return 0

    for r in records:
        current_tag = " [CURRENT]" if r.is_current else ""
        print(f"  Sequence {r.version_sequence}: version '{r.profile_version}'{current_tag}")
        print(f"    Approved By: {r.approved_by} at {r.approved_at.isoformat()}")
        if r.notes:
            print(f"    Notes:       {r.notes}")
    return 0


def _run_show(service: ProfileService, args: argparse.Namespace) -> int:
    if args.version:
        snapshot = service.get_snapshot(args.version)
    else:
        snapshot = service.get_current_snapshot()
        if snapshot is None:
            print("No current approved profile snapshot found.", file=sys.stderr)
            return 2

    print("Profile Snapshot:")
    print(f"  Profile Version: {snapshot.profile_version}")
    print(f"  Candidate ID:    {snapshot.candidate_id}")
    print(f"  Approved By:     {snapshot.approval_metadata.approved_by}")
    print(f"  Approved At:     {snapshot.approval_metadata.approved_at.isoformat()}")
    print(f"  Facts Count:     {len(snapshot.evidence_records)}")

    if args.export:
        dest = Path(args.export)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        print(f"  Exported to:     {dest.resolve()}")

    return 0


def _run_resolve(service: ProfileService, args: argparse.Namespace) -> int:
    version = args.version
    fact_id = uuid.UUID(args.fact_id)
    fact = service.resolve_candidate_reference((version, fact_id))

    print("C08 Citation Resolution: SUCCESS")
    print(f"  Profile Version: {version}")
    print(f"  Fact ID:         {fact.fact_id}")
    print(f"  Title:           {fact.title}")
    print(f"  Kind:            {fact.kind.value}")
    if fact.organization:
        print(f"  Organization:    {fact.organization}")
    print(f"  Provenance:      {fact.provenance}")
    print(f"  Allowed Uses:    {fact.allowed_uses}")
    return 0

