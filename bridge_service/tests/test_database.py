"""Tests for the SQLite database layer."""

import os
import sqlite3
import tempfile

import pytest

# Adjust import path for tests
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import Database


@pytest.fixture
def tmp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = Database(db_path)
    db.init_db()
    yield db, db_path
    db.close()
    os.unlink(db_path)


# ── Initialization ────────────────────────────────────────────────


class TestDatabaseInit:
    def test_init_creates_tables(self, tmp_db):
        db, _ = tmp_db
        # Check all 5 tables exist
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}
        expected = {"ai_providers", "mt5_targets", "deployments", "backups", "comparisons"}
        assert expected <= table_names

    def test_init_is_idempotent(self, tmp_db):
        db, db_path = tmp_db
        # Calling init_db again should not fail
        db.init_db()
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}
        assert len(table_names) == 5


# ── Provider CRUD ────────────────────────────────────────────────


class TestProviderCRUD:
    def test_create_provider(self, tmp_db):
        db, _ = tmp_db
        provider = db.create_provider(
            name="OpenAI", type="openai", base_url="https://api.openai.com",
            api_key="sk-test", model="gpt-4o", is_default=True
        )
        assert provider["id"] is not None
        assert provider["name"] == "OpenAI"
        assert provider["type"] == "openai"
        assert provider["is_default"] == 1
        assert provider["created_at"] is not None

    def test_get_provider(self, tmp_db):
        db, _ = tmp_db
        created = db.create_provider(name="Gemini", type="gemini", model="gemini-pro")
        fetched = db.get_provider(created["id"])
        assert fetched is not None
        assert fetched["name"] == "Gemini"

    def test_get_provider_not_found(self, tmp_db):
        db, _ = tmp_db
        assert db.get_provider(999) is None

    def test_list_providers(self, tmp_db):
        db, _ = tmp_db
        db.create_provider(name="A", type="openai")
        db.create_provider(name="B", type="anthropic")
        providers = db.list_providers()
        assert len(providers) == 2

    def test_update_provider(self, tmp_db):
        db, _ = tmp_db
        created = db.create_provider(name="Old", type="openai")
        updated = db.update_provider(created["id"], name="New", model="gpt-4o")
        assert updated["name"] == "New"
        assert updated["model"] == "gpt-4o"

    def test_delete_provider(self, tmp_db):
        db, _ = tmp_db
        created = db.create_provider(name="X", type="openai")
        db.delete_provider(created["id"])
        assert db.get_provider(created["id"]) is None


# ── Target CRUD ──────────────────────────────────────────────────


class TestTargetCRUD:
    def test_create_target(self, tmp_db):
        db, _ = tmp_db
        target = db.create_target(
            name="Main MT5", install_path="C:/MT5", data_path="C:/MT5/Data",
            is_portable=False, is_active=True
        )
        assert target["id"] is not None
        assert target["name"] == "Main MT5"
        assert target["install_path"] == "C:/MT5"
        assert target["created_at"] is not None

    def test_get_target(self, tmp_db):
        db, _ = tmp_db
        created = db.create_target(name="T", install_path="/x")
        fetched = db.get_target(created["id"])
        assert fetched is not None
        assert fetched["name"] == "T"

    def test_get_target_not_found(self, tmp_db):
        db, _ = tmp_db
        assert db.get_target(999) is None

    def test_list_targets(self, tmp_db):
        db, _ = tmp_db
        db.create_target(name="A", install_path="/a")
        db.create_target(name="B", install_path="/b")
        targets = db.list_targets()
        assert len(targets) == 2

    def test_update_target(self, tmp_db):
        db, _ = tmp_db
        created = db.create_target(name="Old", install_path="/old")
        updated = db.update_target(created["id"], name="New")
        assert updated["name"] == "New"

    def test_delete_target(self, tmp_db):
        db, _ = tmp_db
        created = db.create_target(name="X", install_path="/x")
        db.delete_target(created["id"])
        assert db.get_target(created["id"]) is None


# ── Deployment CRUD ──────────────────────────────────────────────


class TestDeploymentCRUD:
    def _make_target_and_provider(self, db):
        t = db.create_target(name="T", install_path="/t")
        p = db.create_provider(name="P", type="openai")
        return t, p

    def test_create_deployment(self, tmp_db):
        db, _ = tmp_db
        target, provider = self._make_target_and_provider(db)
        dep = db.create_deployment(
            strategy_name="MyStrategy",
            mt5_target_id=target["id"],
            ai_provider_id=provider["id"],
            status="pending"
        )
        assert dep["id"] is not None
        assert dep["strategy_name"] == "MyStrategy"
        assert dep["status"] == "pending"
        assert dep["errors_found"] == 0
        assert dep["errors_fixed"] == 0
        assert dep["created_at"] is not None

    def test_get_deployment(self, tmp_db):
        db, _ = tmp_db
        t, p = self._make_target_and_provider(db)
        created = db.create_deployment(
            strategy_name="S", mt5_target_id=t["id"],
            ai_provider_id=p["id"], status="running"
        )
        fetched = db.get_deployment(created["id"])
        assert fetched is not None
        assert fetched["strategy_name"] == "S"

    def test_get_deployment_not_found(self, tmp_db):
        db, _ = tmp_db
        assert db.get_deployment(999) is None

    def test_list_deployments(self, tmp_db):
        db, _ = tmp_db
        t, p = self._make_target_and_provider(db)
        db.create_deployment(strategy_name="A", mt5_target_id=t["id"],
                             ai_provider_id=p["id"], status="pending")
        db.create_deployment(strategy_name="B", mt5_target_id=t["id"],
                             ai_provider_id=p["id"], status="done")
        deps = db.list_deployments()
        assert len(deps) == 2

    def test_update_deployment(self, tmp_db):
        db, _ = tmp_db
        t, p = self._make_target_and_provider(db)
        created = db.create_deployment(
            strategy_name="S", mt5_target_id=t["id"],
            ai_provider_id=p["id"], status="pending"
        )
        updated = db.update_deployment(
            created["id"], status="done", errors_found=3, errors_fixed=2
        )
        assert updated["status"] == "done"
        assert updated["errors_found"] == 3
        assert updated["errors_fixed"] == 2

    def test_delete_deployment(self, tmp_db):
        db, _ = tmp_db
        t, p = self._make_target_and_provider(db)
        created = db.create_deployment(
            strategy_name="X", mt5_target_id=t["id"],
            ai_provider_id=p["id"], status="pending"
        )
        db.delete_deployment(created["id"])
        assert db.get_deployment(created["id"]) is None


# ── Backup CRUD ──────────────────────────────────────────────────


class TestBackupCRUD:
    def _make_deployment(self, db):
        t = db.create_target(name="T", install_path="/t")
        p = db.create_provider(name="P", type="openai")
        return db.create_deployment(
            strategy_name="S", mt5_target_id=t["id"],
            ai_provider_id=p["id"], status="pending"
        )

    def test_create_backup(self, tmp_db):
        db, _ = tmp_db
        dep = self._make_deployment(db)
        bk = db.create_backup(
            deployment_id=dep["id"],
            strategy_name="S",
            file_path="/backups/S_v1.ex5",
            file_hash="abc123"
        )
        assert bk["id"] is not None
        assert bk["file_path"] == "/backups/S_v1.ex5"
        assert bk["created_at"] is not None

    def test_get_backup(self, tmp_db):
        db, _ = tmp_db
        dep = self._make_deployment(db)
        created = db.create_backup(
            deployment_id=dep["id"], strategy_name="S",
            file_path="/x", file_hash="h"
        )
        fetched = db.get_backup(created["id"])
        assert fetched is not None

    def test_list_backups_by_deployment(self, tmp_db):
        db, _ = tmp_db
        dep = self._make_deployment(db)
        db.create_backup(deployment_id=dep["id"], strategy_name="S",
                         file_path="/a", file_hash="h1")
        db.create_backup(deployment_id=dep["id"], strategy_name="S",
                         file_path="/b", file_hash="h2")
        backups = db.list_backups(deployment_id=dep["id"])
        assert len(backups) == 2

    def test_delete_backup(self, tmp_db):
        db, _ = tmp_db
        dep = self._make_deployment(db)
        created = db.create_backup(
            deployment_id=dep["id"], strategy_name="S",
            file_path="/x", file_hash="h"
        )
        db.delete_backup(created["id"])
        assert db.get_backup(created["id"]) is None


# ── Comparison CRUD ──────────────────────────────────────────────


class TestComparisonCRUD:
    def _make_deployment(self, db):
        t = db.create_target(name="T", install_path="/t")
        p = db.create_provider(name="P", type="openai")
        return db.create_deployment(
            strategy_name="S", mt5_target_id=t["id"],
            ai_provider_id=p["id"], status="done"
        )

    def test_create_comparison(self, tmp_db):
        db, _ = tmp_db
        dep = self._make_deployment(db)
        cmp = db.create_comparison(
            deployment_id=dep["id"],
            sqx_metrics='{"profit": 1000}',
            mt5_metrics='{"profit": 950}',
            deltas='{"profit": -50}',
            status="mismatch",
            report_path="/reports/cmp.html"
        )
        assert cmp["id"] is not None
        assert cmp["status"] == "mismatch"
        assert cmp["created_at"] is not None

    def test_get_comparison(self, tmp_db):
        db, _ = tmp_db
        dep = self._make_deployment(db)
        created = db.create_comparison(
            deployment_id=dep["id"], status="match"
        )
        fetched = db.get_comparison(created["id"])
        assert fetched is not None
        assert fetched["status"] == "match"

    def test_list_comparisons_by_deployment(self, tmp_db):
        db, _ = tmp_db
        dep = self._make_deployment(db)
        db.create_comparison(deployment_id=dep["id"], status="match")
        db.create_comparison(deployment_id=dep["id"], status="mismatch")
        comparisons = db.list_comparisons(deployment_id=dep["id"])
        assert len(comparisons) == 2

    def test_delete_comparison(self, tmp_db):
        db, _ = tmp_db
        dep = self._make_deployment(db)
        created = db.create_comparison(deployment_id=dep["id"], status="x")
        db.delete_comparison(created["id"])
        assert db.get_comparison(created["id"]) is None
