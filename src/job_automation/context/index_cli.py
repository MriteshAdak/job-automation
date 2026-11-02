"""CLI subcommand handlers for local vector and keyword indexing (CONTEXT-03)."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from job_automation.configuration import load_config
from job_automation.context.chunk_service import EvidenceChunker
from job_automation.context.index_service import IndexService
from job_automation.context.index_settings import load_index_settings
from job_automation.contracts.evidence_chunks import ChunkBuildRequest, ChunkSet
from job_automation.contracts.retrieval_index import (
    EmbeddingConfiguration,
    IndexBuildRequest,
    IndexSettings,
)
from job_automation.models.provider import LocalModelProvider
from job_automation.profile.service import ProfileService
from job_automation.storage.engine import StorageEngine


def register_context_subparsers(subparsers: argparse._SubParsersAction) -> None:
    """Register context command group and subcommands."""
    context_parser = subparsers.add_parser(
        "context",
        help="Context preparation, chunking, and indexing commands",
    )
    context_sub = context_parser.add_subparsers(
        dest="context_command",
        help="Context actions",
    )

    # context index ...
    index_parser = context_sub.add_parser("index", help="Index construction and status commands")
    index_sub = index_parser.add_subparsers(dest="index_action", help="Index operations")

    # 1. build
    build_parser = index_sub.add_parser("build", help="Build vector and keyword index")
    build_parser.add_argument("--candidate-id", required=True, type=str, help="Candidate UUID")
    build_parser.add_argument("--purpose", required=True, type=str, help="Inclusion purpose")
    build_parser.add_argument("--profile-version", default=None, type=str, help="Profile version (default: current)")
    build_parser.add_argument("--chunk-set", default=None, type=str, help="Optional prebuilt ChunkSet JSON file")
    build_parser.add_argument("--model-config", default=None, type=str, help="Path to EmbeddingConfiguration JSON")
    build_parser.add_argument("--activate", action="store_true", help="Auto-activate after successful build")
    build_parser.add_argument("--config", default=None, type=str, help="Path to app configuration JSON")
    build_parser.add_argument("--data-root", default=None, type=str, help="Override runtime data root")

    # 2. status
    status_parser = index_sub.add_parser("status", help="Show index status for candidate and purpose")
    status_parser.add_argument("--candidate-id", required=True, type=str, help="Candidate UUID")
    status_parser.add_argument("--purpose", required=True, type=str, help="Inclusion purpose")
    status_parser.add_argument("--config", default=None, type=str, help="Path to app configuration JSON")
    status_parser.add_argument("--data-root", default=None, type=str, help="Override runtime data root")

    # 3. verify
    verify_parser = index_sub.add_parser("verify", help="Verify on-disk index payload integrity")
    verify_parser.add_argument("--candidate-id", required=True, type=str, help="Candidate UUID")
    verify_parser.add_argument("--purpose", required=True, type=str, help="Inclusion purpose")
    verify_parser.add_argument("--config", default=None, type=str, help="Path to app configuration JSON")
    verify_parser.add_argument("--data-root", default=None, type=str, help="Override runtime data root")

    # 4. cleanup
    cleanup_parser = index_sub.add_parser("cleanup", help="Clean up retired index generations")
    cleanup_parser.add_argument("--candidate-id", required=True, type=str, help="Candidate UUID")
    cleanup_parser.add_argument("--purpose", default=None, type=str, help="Inclusion purpose (optional)")
    cleanup_parser.add_argument("--retention", default=2, type=int, help="Number of retired generations to keep")
    cleanup_parser.add_argument("--config", default=None, type=str, help="Path to app configuration JSON")
    cleanup_parser.add_argument("--data-root", default=None, type=str, help="Override runtime data root")


def handle_context_commands(args: argparse.Namespace) -> int:
    """Dispatch context subcommands."""
    if args.context_command != "index":
        print(f"Unknown context command: {args.context_command}", file=sys.stderr)
        return 2

    config, paths = load_config(args.config, args.data_root)
    engine = StorageEngine.from_config(config, paths)
    engine.migrate()

    try:
        # Build IndexService
        provider = LocalModelProvider.from_config(config)
        service = IndexService(
            indexes_dir=paths.indexes_dir,
            repository=engine.context_indexes,
            provider=provider,
        )

        candidate_id = uuid.UUID(args.candidate_id)

        if args.index_action == "build":
            # Load or resolve ChunkSet
            chunk_set: ChunkSet
            profile_ver = args.profile_version

            if args.chunk_set:
                p = Path(args.chunk_set).resolve()
                chunk_set = ChunkSet.model_validate_json(p.read_text(encoding="utf-8"))
                profile_ver = chunk_set.profile_version
            else:
                profile_svc = ProfileService.from_engine(engine)
                if profile_ver:
                    snapshot = profile_svc.get_snapshot(version=profile_ver)
                else:
                    snapshot = profile_svc.get_current_snapshot(candidate_id=candidate_id)
                if snapshot is None:
                    print(f"No profile snapshot found for candidate {candidate_id}", file=sys.stderr)
                    return 2
                chunker = EvidenceChunker()
                chunk_req = ChunkBuildRequest(
                    snapshot=snapshot,
                    purpose=args.purpose,
                )
                res, chunk_err = chunker.build(chunk_req)
                if chunk_err or res is None:
                    print(f"Chunking failed: {chunk_err}", file=sys.stderr)
                    return 2
                chunk_set = res
                profile_ver = snapshot.profile_version

            # Load embedding config
            if args.model_config:
                mp = Path(args.model_config).resolve()
                emb_config = EmbeddingConfiguration.model_validate_json(mp.read_text(encoding="utf-8"))
            else:
                # Fallback to provider model settings if available
                emb_config = EmbeddingConfiguration(
                    model_identifier="nomic-embed-text",
                    dimension=768,
                    verification_provenance="uncalibrated_cli_fallback",
                )

            # Load index settings
            index_settings = load_index_settings(paths.index_settings_path)

            req = IndexBuildRequest(
                candidate_id=candidate_id,
                profile_version=profile_ver,
                purpose=args.purpose,
                chunk_set=chunk_set,
                embedding_config=emb_config,
                settings=index_settings,
            )

            build_res, build_err = service.build(req, auto_activate=args.activate)
            if build_err or build_res is None:
                print(f"Index build failed: {build_err}", file=sys.stderr)
                return 2

            print("Index build: SUCCESS")
            print(f"  Generation ID:     {build_res.generation_id}")
            print(f"  Row Count:         {build_res.manifest.row_count}")
            print(f"  Dimension:         {build_res.manifest.dimension}")
            print(f"  Logical Hash:      {build_res.manifest.logical_build_fingerprint}")
            print(f"  Artifact Hash:     {build_res.manifest.artifact_fingerprint}")
            print(f"  Activated:         {args.activate}")
            return 0

        elif args.index_action == "status":
            stat = service.status(candidate_id, args.purpose)
            print("Index status:")
            print(json.dumps(stat, indent=2))
            return 0

        elif args.index_action == "verify":
            ok, msg = service.verify(candidate_id, args.purpose)
            if ok:
                print(f"Index verify: OK\n  {msg}")
                return 0
            else:
                print(f"Index verify: FAILED\n  {msg}", file=sys.stderr)
                return 2

        elif args.index_action == "cleanup":
            rep = service.cleanup(
                candidate_id=candidate_id,
                purpose=args.purpose,
                retention_count=args.retention,
            )
            print("Index cleanup: COMPLETED")
            print(json.dumps(rep, indent=2))
            return 0

        else:
            print(f"Unknown index action: {args.index_action}", file=sys.stderr)
            return 2

    finally:
        engine.close()
