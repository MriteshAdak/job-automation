"""Tests for conservative company identity resolution and alias scoping."""

from __future__ import annotations

from pathlib import Path

from job_automation.identity.companies import (
    normalize_company_name,
    resolve_company_identity,
)
from job_automation.storage.engine import StorageEngine


class TestCompanies:
    def test_normalize_company_name(self) -> None:
        assert normalize_company_name("Acme GmbH") == "acme"
        assert normalize_company_name("Acme AG") == "acme"
        assert normalize_company_name("Acme GmbH & Co. KG") == "acme"
        assert normalize_company_name("Acme Inc.") == "acme"
        assert normalize_company_name("Acme LLC") == "acme"
        assert normalize_company_name("Müller Beratung GmbH") == "müller beratung"

        # Distinct substantive tokens remain separate
        assert normalize_company_name("Nordlicht GmbH") != normalize_company_name("Nordlicht Services GmbH")

    def test_stable_company_uuid_reuse(self, tmp_path: Path) -> None:
        db_path = tmp_path / "comp_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()

            id1, name1 = resolve_company_identity(
                company_name_hint="Alpha Logistics GmbH",
                company_id_hint="comp_99",
                provider="arbeitnow",
                board_id="default",
                identity_repo=engine.identity,
            )

            # Re-resolution with same provider company ID reuses UUID
            id2, name2 = resolve_company_identity(
                company_name_hint="Alpha Logistics Europe",
                company_id_hint="comp_99",
                provider="arbeitnow",
                board_id="default",
                identity_repo=engine.identity,
            )
            assert id1 == id2
            assert name2 == "Alpha Logistics Europe"

    def test_provider_company_id_scoping_across_boards(self, tmp_path: Path) -> None:
        """Identical provider company IDs in different providers/boards are not assumed identical."""
        db_path = tmp_path / "scope_comp_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()

            id_board_a, _ = resolve_company_identity(
                company_name_hint="Tenant A Company",
                company_id_hint="0012",
                provider="provider_x",
                board_id="board_a",
                identity_repo=engine.identity,
            )

            id_board_b, _ = resolve_company_identity(
                company_name_hint="Tenant B Company",
                company_id_hint="0012",
                provider="provider_x",
                board_id="board_b",
                identity_repo=engine.identity,
            )

            # Different board namespaces produce distinct company UUIDs
            assert id_board_a != id_board_b

    def test_conservative_distinction_for_similar_names(self, tmp_path: Path) -> None:
        """'Nordlicht GmbH' and 'Nordlicht Services GmbH' remain separate entities."""
        db_path = tmp_path / "similar_comp_test.db"
        with StorageEngine(db_path=db_path) as engine:
            engine.initialize_schema()

            id1, _ = resolve_company_identity(
                company_name_hint="Nordlicht GmbH",
                company_id_hint=None,
                provider="manual",
                board_id="default",
                identity_repo=engine.identity,
            )

            id2, _ = resolve_company_identity(
                company_name_hint="Nordlicht Services GmbH",
                company_id_hint=None,
                provider="manual",
                board_id="default",
                identity_repo=engine.identity,
            )

            assert id1 != id2

