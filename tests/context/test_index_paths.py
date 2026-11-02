"""Unit tests for path containment and security in CONTEXT-03."""

from __future__ import annotations

from pathlib import Path
import pytest

from job_automation.context.index_capacity import validate_index_path
from job_automation.context.index_errors import IndexConfigurationError


def test_validate_index_path_valid_subdirectory(tmp_path: Path) -> None:
    base = tmp_path / "indexes"
    base.mkdir(parents=True)
    target = base / "candidate_123" / "assessment" / "gen_456"

    validated = validate_index_path(target, base)
    assert validated == target.resolve()


def test_validate_index_path_rejects_escape(tmp_path: Path) -> None:
    base = tmp_path / "indexes"
    base.mkdir(parents=True)
    target = base / ".." / "other_dir"

    with pytest.raises(IndexConfigurationError) as exc:
        validate_index_path(target, base)
    assert "escapes configured index directory" in exc.value.message


def test_validate_index_path_rejects_unc_path(tmp_path: Path) -> None:
    base = tmp_path / "indexes"
    unc_target = "\\\\network_server\\share\\index"

    with pytest.raises(IndexConfigurationError) as exc:
        validate_index_path(unc_target, base)
    assert "UNC/network paths are not permitted" in exc.value.message


def test_validate_index_path_with_spaces_and_umlauts(tmp_path: Path) -> None:
    base = tmp_path / "Index Daten Prüfung äöü"
    base.mkdir(parents=True)
    target = base / "Kandidat Max" / "Bewerbung" / "gen_1"

    validated = validate_index_path(target, base)
    assert "Index Daten Prüfung äöü" in str(validated)

