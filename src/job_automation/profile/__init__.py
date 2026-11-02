"""Candidate evidence and profile snapshot management component (PROFILE-01).

Owns:
- Unapproved draft intake and stable identity management.
- Provenance recording and evidence file storage.
- Explicit human approval and immutable C01 publication.
- Shared purpose-aware inclusion rules for JSON and RAG consumers.
- Version history, structural diffs, and exact historical C08 reference resolution.
"""

from __future__ import annotations

from job_automation.profile.errors import (
    EvidenceStoreError,
    FactNotFoundError,
    InclusionConflictError,
    ProfileApprovalError,
    ProfileConflictError,
    ProfileError,
    ProfileNotFoundError,
    ProfileValidationError,
)
from job_automation.profile.evidence_store import EvidenceStore
from job_automation.profile.history import compare_snapshots, list_version_history
from job_automation.profile.inclusion import InclusionRules
from job_automation.profile.intake import parse_draft_intake
from job_automation.profile.models import (
    DEFAULT_RULE_VERSION,
    SUPPORTED_PURPOSES,
    DraftFact,
    DraftProfile,
    FactDiff,
    ProfileDiff,
    ProfileInclusionView,
    ProfileVersionRecord,
    ProvenanceRecord,
)
from job_automation.profile.provenance import create_provenance_record
from job_automation.profile.references import resolve_candidate_evidence_reference
from job_automation.profile.service import ProfileService

__all__ = [
    "DEFAULT_RULE_VERSION",
    "SUPPORTED_PURPOSES",
    "DraftFact",
    "DraftProfile",
    "EvidenceStore",
    "EvidenceStoreError",
    "FactDiff",
    "FactNotFoundError",
    "InclusionConflictError",
    "InclusionRules",
    "ProfileApprovalError",
    "ProfileConflictError",
    "ProfileDiff",
    "ProfileError",
    "ProfileInclusionView",
    "ProfileNotFoundError",
    "ProfileService",
    "ProfileValidationError",
    "ProfileVersionRecord",
    "ProvenanceRecord",
    "compare_snapshots",
    "create_provenance_record",
    "list_version_history",
    "parse_draft_intake",
    "resolve_candidate_evidence_reference",
]

