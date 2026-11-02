"""Salesforce project metadata inventory, ownership classification, and retrieval staging audit (SF-04-S03).

Enforces:
- Strict classification of metadata members against metadata-ownership.json:
  project-owned, shared-dependency, unrelated-protected, managed-package-controlled, unknown.
- Detection and quarantine of unowned nested children (e.g. extra object fields, standard profiles).
- Static secret scanning for client secrets, private keys, refresh tokens, and credentials.
- Deterministic SHA-256 digest computation over project-owned metadata files.
- Safe semantic comparison between staged retrieval output and repository source tree.
- Zero blind overwriting of salesforce/force-app/.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "salesforce"
    / "metadata-ownership.json"
)

# Patterns that indicate secrets or prohibited credentials in retrieved metadata
SECRET_PATTERNS = [
    re.compile(r"<(?:clientSecret|consumerSecret|privateKey|certificate|password)>\s*[^<\s]+", re.IGNORECASE),
    re.compile(r"(?:BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY|oauth_token|refresh_token\s*=)", re.IGNORECASE),
    re.compile(r"00D[A-Za-z0-9]{12,15}![A-Za-z0-9._]+", re.IGNORECASE),  # session token pattern
]


def load_ownership_registry(path: Path | str | None = None) -> dict[str, Any]:
    """Load metadata ownership classification registry."""
    reg_path = Path(path).resolve() if path else DEFAULT_REGISTRY_PATH
    if not reg_path.is_file():
        raise FileNotFoundError(f"Metadata ownership registry not found at: {reg_path}")

    with reg_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def classify_metadata_member(
    metadata_type: str,
    member_name: str,
    registry: dict[str, Any],
) -> str:
    """Classify a metadata member into an ownership category."""
    project_owned = registry.get("project_owned", {})
    if metadata_type in project_owned:
        owned_list = project_owned[metadata_type]
        if member_name in owned_list or "*" in owned_list:
            return "project-owned"

    unrelated = registry.get("unrelated_protected", {})
    if metadata_type in unrelated:
        unrelated_list = unrelated[metadata_type]
        if member_name in unrelated_list or "*" in unrelated_list:
            return "unrelated-protected"

    shared = registry.get("shared_dependencies", {})
    if metadata_type in shared:
        shared_list = shared[metadata_type]
        if member_name in shared_list or "*" in shared_list:
            return "shared-dependency"

    managed = registry.get("managed_package_controlled", {})
    if metadata_type in managed:
        return "managed-package-controlled"

    return "unknown"


def scan_file_for_secrets(file_path: Path) -> list[str]:
    """Inspect text content of a metadata file for secret or credential patterns."""
    findings: list[str] = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        findings.append(f"Could not read '{file_path.name}': {exc}")
        return findings

    for pat in SECRET_PATTERNS:
        match = pat.search(content)
        if match:
            findings.append(
                f"Potential secret/credential pattern detected in '{file_path.name}': {match.group(0)[:20]}..."
            )
    return findings


def audit_staged_metadata(
    staged_root: Path | str,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Audit staged metadata files against the ownership registry.

    Identifies:
    - project-owned files
    - quarantine candidates (unowned files or unrelated org metadata)
    - security findings (credentials/tokens/broad profiles)
    """
    root = Path(staged_root).resolve()
    reg = registry or load_ownership_registry()

    project_owned_files: list[str] = []
    quarantine_files: list[str] = []
    security_findings: list[str] = []
    classified_members: dict[str, list[str]] = {
        "project-owned": [],
        "shared-dependency": [],
        "unrelated-protected": [],
        "managed-package-controlled": [],
        "unknown": [],
    }

    if not root.is_dir():
        return {
            "staged_root": str(root),
            "is_valid": False,
            "error": f"Staged directory does not exist: {root}",
            "project_owned_files": [],
            "quarantine_files": [],
            "security_findings": [],
            "classified_members": classified_members,
        }

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        rel_path = path.relative_to(root).as_posix()

        # Scan for secrets
        secrets = scan_file_for_secrets(path)
        if secrets:
            security_findings.extend(secrets)
            quarantine_files.append(rel_path)
            continue

        # Check for profile files
        if path.suffix == ".profile-meta.xml" or "profiles" in path.parts:
            security_findings.append(f"Broad profile detected in staged retrieval: '{rel_path}'")
            quarantine_files.append(rel_path)
            classified_members["unrelated-protected"].append(rel_path)
            continue

        # Match member classification
        member_type, member_name = _infer_member_info(path, root)
        cat = classify_metadata_member(member_type, member_name, reg)
        classified_members[cat].append(rel_path)

        if cat == "project-owned":
            project_owned_files.append(rel_path)
        else:
            quarantine_files.append(rel_path)

    is_valid = len(quarantine_files) == 0 and len(security_findings) == 0

    return {
        "staged_root": str(root),
        "is_valid": is_valid,
        "project_owned_files": project_owned_files,
        "quarantine_files": quarantine_files,
        "security_findings": security_findings,
        "classified_members": classified_members,
    }


def compute_metadata_digest(metadata_root: Path | str) -> str:
    """Compute a deterministic SHA-256 digest across all project-owned metadata files."""
    root = Path(metadata_root).resolve()
    if not root.is_dir():
        return ""

    file_hashes: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.name.startswith("."):
            rel = path.relative_to(root).as_posix()
            data = path.read_bytes()
            h = hashlib.sha256(data).hexdigest()
            file_hashes.append(f"{rel}:{h}")

    combined = "\n".join(file_hashes).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def compare_staged_with_repository(
    staged_root: Path | str,
    repo_root: Path | str,
) -> dict[str, Any]:
    """Compare staged metadata with repository source format without modifying files."""
    staged = Path(staged_root).resolve()
    repo = Path(repo_root).resolve()

    identical: list[str] = []
    modified: list[str] = []
    staged_only: list[str] = []
    repo_only: list[str] = []

    staged_files = {p.relative_to(staged).as_posix(): p for p in staged.rglob("*") if p.is_file()}
    repo_files = {p.relative_to(repo).as_posix(): p for p in repo.rglob("*") if p.is_file()}

    all_keys = sorted(set(staged_files.keys()) | set(repo_files.keys()))

    for key in all_keys:
        if key in staged_files and key in repo_files:
            if staged_files[key].read_bytes() == repo_files[key].read_bytes():
                identical.append(key)
            else:
                modified.append(key)
        elif key in staged_files:
            staged_only.append(key)
        else:
            repo_only.append(key)

    has_diff = len(modified) > 0 or len(staged_only) > 0 or len(repo_only) > 0

    return {
        "identical_files": identical,
        "modified_files": modified,
        "staged_only_files": staged_only,
        "repo_only_files": repo_only,
        "has_unreviewed_changes": has_diff,
        "summary": (
            f"{len(identical)} identical, {len(modified)} modified, "
            f"{len(staged_only)} staged-only, {len(repo_only)} repo-only"
        ),
    }


def check_cli_availability() -> tuple[bool, str]:
    """Check whether Salesforce CLI ('sf' or 'sfdx') is executable on the current system."""
    cli_bin = shutil.which("sf") or shutil.which("sfdx")
    if not cli_bin:
        return False, "Salesforce CLI ('sf' or 'sfdx') is not installed or not on system PATH."

    try:
        proc = subprocess.run(
            [cli_bin, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode == 0:
            return True, proc.stdout.strip()
        return False, f"Salesforce CLI check failed with returncode {proc.returncode}: {proc.stderr.strip()}"
    except Exception as exc:
        return False, f"Salesforce CLI execution error: {exc}"


def _infer_member_info(file_path: Path, root: Path) -> tuple[str, str]:
    """Infer metadata type and member name from file path within source format."""
    rel_parts = file_path.relative_to(root).parts
    filename = file_path.name

    # Check for objects/ObjectName/fields/FieldName.field-meta.xml
    if "objects" in rel_parts:
        obj_idx = rel_parts.index("objects")
        if len(rel_parts) > obj_idx + 1:
            obj_name = rel_parts[obj_idx + 1]
            if "fields" in rel_parts:
                field_name = filename.split(".")[0]
                return "CustomField", f"{obj_name}.{field_name}"
            elif "validationRules" in rel_parts:
                rule_name = filename.split(".")[0]
                return "ValidationRule", f"{obj_name}.{rule_name}"
            elif "compactLayouts" in rel_parts:
                cl_name = filename.split(".")[0]
                return "CompactLayout", f"{obj_name}.{cl_name}"
            elif "listViews" in rel_parts:
                lv_name = filename.split(".")[0]
                return "ListView", f"{obj_name}.{lv_name}"
            elif filename.endswith(".object-meta.xml"):
                return "CustomObject", obj_name

    # Check for permissionsets
    if "permissionsets" in rel_parts:
        ps_name = filename.split(".")[0]
        return "PermissionSet", ps_name

    # Check for layouts
    if "layouts" in rel_parts:
        layout_name = filename.split(".")[0]
        return "Layout", layout_name

    # Check for flexipages
    if "flexipages" in rel_parts:
        fp_name = filename.split(".")[0]
        return "FlexiPage", fp_name

    # Check for tabs
    if "tabs" in rel_parts:
        tab_name = filename.split(".")[0]
        return "CustomTab", tab_name

    # Check for applications
    if "applications" in rel_parts:
        app_name = filename.split(".")[0]
        return "CustomApplication", app_name

    # Check for reportTypes
    if "reportTypes" in rel_parts:
        rt_name = filename.split(".")[0]
        return "ReportType", rt_name

    # Check for reports
    if "reports" in rel_parts:
        rep_idx = rel_parts.index("reports")
        if len(rel_parts) > rep_idx + 2:
            folder = rel_parts[rep_idx + 1]
            rep_name = filename.split(".")[0]
            return "Report", f"{folder}/{rep_name}"
        elif filename.endswith(".reportFolder-meta.xml"):
            folder_name = filename.split(".")[0]
            return "ReportFolder", folder_name

    # Check for externalClientApps
    if "externalClientApps" in rel_parts:
        eca_name = filename.split(".")[0]
        return "ExternalClientApplication", eca_name

    if "extlClntAppOauthSettings" in rel_parts:
        eca_name = filename.split(".")[0]
        return "ExtlClntAppOauthSettings", eca_name

    if "extlClntAppOauthPolicies" in rel_parts:
        eca_name = filename.split(".")[0]
        return "ExtlClntAppOauthConfigurablePolicies", eca_name

    return "Unknown", filename

