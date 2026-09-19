"""SQLite database layer for the SQX-MT5 Bridge Service."""

import sqlite3
from datetime import datetime, timezone


class Database:
    """SQLite database with CRUD for all bridge tables."""

    def __init__(self, db_path: str = "bridge_service.db"):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    # ── Connection helpers ────────────────────────────────────────

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._get_conn().execute(sql, params)

    def commit(self):
        self._get_conn().commit()

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ── Schema creation ───────────────────────────────────────────

    def init_db(self):
        """Create all tables if they don't already exist."""
        conn = self._get_conn()
        conn.executescript(SCHEMA_SQL)
        conn.commit()

    # ── Helper to convert Row to dict ────────────────────────────

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        return dict(row)

    # ── Provider CRUD ────────────────────────────────────────────

    def create_provider(
        self,
        name: str,
        type: str,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        is_default: bool = False,
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.execute(
            """INSERT INTO ai_providers
               (name, type, base_url, api_key, model, is_default, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (name, type, base_url, api_key, model, int(is_default), now),
        )
        self.commit()
        return self.get_provider(cur.lastrowid)  # type: ignore[arg-type]

    def get_provider(self, provider_id: int) -> dict | None:
        row = self.execute(
            "SELECT * FROM ai_providers WHERE id = ?", (provider_id,)
        ).fetchone()
        return self._row_to_dict(row)

    def list_providers(self) -> list[dict]:
        rows = self.execute("SELECT * FROM ai_providers ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def update_provider(self, provider_id: int, **fields) -> dict | None:
        allowed = {"name", "type", "base_url", "api_key", "model", "is_default"}
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return self.get_provider(provider_id)
        # Convert bool to int for is_default
        if "is_default" in filtered:
            filtered["is_default"] = int(filtered["is_default"])
        set_clause = ", ".join(f"{k} = ?" for k in filtered)
        values = list(filtered.values()) + [provider_id]
        self.execute(f"UPDATE ai_providers SET {set_clause} WHERE id = ?", tuple(values))
        self.commit()
        return self.get_provider(provider_id)

    def delete_provider(self, provider_id: int):
        self.execute("DELETE FROM ai_providers WHERE id = ?", (provider_id,))
        self.commit()

    # ── Target CRUD ──────────────────────────────────────────────

    def create_target(
        self,
        name: str,
        install_path: str,
        data_path: str | None = None,
        is_portable: bool = False,
        is_active: bool = True,
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.execute(
            """INSERT INTO mt5_targets
               (name, install_path, data_path, is_portable, is_active, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, install_path, data_path, int(is_portable), int(is_active), now),
        )
        self.commit()
        return self.get_target(cur.lastrowid)

    def get_target(self, target_id: int) -> dict | None:
        row = self.execute(
            "SELECT * FROM mt5_targets WHERE id = ?", (target_id,)
        ).fetchone()
        return self._row_to_dict(row)

    def list_targets(self) -> list[dict]:
        rows = self.execute("SELECT * FROM mt5_targets ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def update_target(self, target_id: int, **fields) -> dict | None:
        allowed = {"name", "install_path", "data_path", "is_portable", "is_active"}
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return self.get_target(target_id)
        if "is_portable" in filtered:
            filtered["is_portable"] = int(filtered["is_portable"])
        if "is_active" in filtered:
            filtered["is_active"] = int(filtered["is_active"])
        set_clause = ", ".join(f"{k} = ?" for k in filtered)
        values = list(filtered.values()) + [target_id]
        self.execute(f"UPDATE mt5_targets SET {set_clause} WHERE id = ?", tuple(values))
        self.commit()
        return self.get_target(target_id)

    def delete_target(self, target_id: int):
        self.execute("DELETE FROM mt5_targets WHERE id = ?", (target_id,))
        self.commit()

    # ── Deployment CRUD ──────────────────────────────────────────

    def create_deployment(
        self,
        strategy_name: str,
        mt5_target_id: int,
        ai_provider_id: int,
        status: str,
        sqx_version: str | None = None,
        deployed_version: str | None = None,
        errors_found: int = 0,
        errors_fixed: int = 0,
        ai_review_log: str | None = None,
        compilation_log: str | None = None,
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.execute(
            """INSERT INTO deployments
               (strategy_name, mt5_target_id, ai_provider_id, status,
                sqx_version, deployed_version, errors_found, errors_fixed,
                ai_review_log, compilation_log, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (strategy_name, mt5_target_id, ai_provider_id, status,
             sqx_version, deployed_version, errors_found, errors_fixed,
             ai_review_log, compilation_log, now),
        )
        self.commit()
        return self.get_deployment(cur.lastrowid)

    def get_deployment(self, deployment_id: int) -> dict | None:
        row = self.execute(
            "SELECT * FROM deployments WHERE id = ?", (deployment_id,)
        ).fetchone()
        return self._row_to_dict(row)

    def list_deployments(self) -> list[dict]:
        rows = self.execute("SELECT * FROM deployments ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def update_deployment(self, deployment_id: int, **fields) -> dict | None:
        allowed = {
            "strategy_name", "mt5_target_id", "ai_provider_id", "status",
            "sqx_version", "deployed_version", "errors_found", "errors_fixed",
            "ai_review_log", "compilation_log",
        }
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return self.get_deployment(deployment_id)
        set_clause = ", ".join(f"{k} = ?" for k in filtered)
        values = list(filtered.values()) + [deployment_id]
        self.execute(f"UPDATE deployments SET {set_clause} WHERE id = ?", tuple(values))
        self.commit()
        return self.get_deployment(deployment_id)

    def delete_deployment(self, deployment_id: int):
        self.execute("DELETE FROM deployments WHERE id = ?", (deployment_id,))
        self.commit()

    # ── Backup CRUD ──────────────────────────────────────────────

    def create_backup(
        self,
        deployment_id: int,
        strategy_name: str | None = None,
        file_path: str | None = None,
        file_hash: str | None = None,
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.execute(
            """INSERT INTO backups
               (deployment_id, strategy_name, file_path, file_hash, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (deployment_id, strategy_name, file_path, file_hash, now),
        )
        self.commit()
        return self.get_backup(cur.lastrowid)

    def get_backup(self, backup_id: int) -> dict | None:
        row = self.execute(
            "SELECT * FROM backups WHERE id = ?", (backup_id,)
        ).fetchone()
        return self._row_to_dict(row)

    def list_backups(self, deployment_id: int | None = None) -> list[dict]:
        if deployment_id is not None:
            rows = self.execute(
                "SELECT * FROM backups WHERE deployment_id = ? ORDER BY id",
                (deployment_id,),
            ).fetchall()
        else:
            rows = self.execute("SELECT * FROM backups ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def update_backup(self, backup_id: int, **fields) -> dict | None:
        allowed = {"deployment_id", "strategy_name", "file_path", "file_hash"}
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return self.get_backup(backup_id)
        set_clause = ", ".join(f"{k} = ?" for k in filtered)
        values = list(filtered.values()) + [backup_id]
        self.execute(f"UPDATE backups SET {set_clause} WHERE id = ?", tuple(values))
        self.commit()
        return self.get_backup(backup_id)

    def delete_backup(self, backup_id: int):
        self.execute("DELETE FROM backups WHERE id = ?", (backup_id,))
        self.commit()

    # ── Comparison CRUD ──────────────────────────────────────────

    def create_comparison(
        self,
        deployment_id: int,
        sqx_metrics: str | None = None,
        mt5_metrics: str | None = None,
        deltas: str | None = None,
        status: str | None = None,
        report_path: str | None = None,
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.execute(
            """INSERT INTO comparisons
               (deployment_id, sqx_metrics, mt5_metrics, deltas, status,
                report_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (deployment_id, sqx_metrics, mt5_metrics, deltas, status,
             report_path, now),
        )
        self.commit()
        return self.get_comparison(cur.lastrowid)

    def get_comparison(self, comparison_id: int) -> dict | None:
        row = self.execute(
            "SELECT * FROM comparisons WHERE id = ?", (comparison_id,)
        ).fetchone()
        return self._row_to_dict(row)

    def list_comparisons(self, deployment_id: int | None = None) -> list[dict]:
        if deployment_id is not None:
            rows = self.execute(
                "SELECT * FROM comparisons WHERE deployment_id = ? ORDER BY id",
                (deployment_id,),
            ).fetchall()
        else:
            rows = self.execute("SELECT * FROM comparisons ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def update_comparison(self, comparison_id: int, **fields) -> dict | None:
        allowed = {"deployment_id", "sqx_metrics", "mt5_metrics", "deltas", "status", "report_path"}
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return self.get_comparison(comparison_id)
        set_clause = ", ".join(f"{k} = ?" for k in filtered)
        values = list(filtered.values()) + [comparison_id]
        self.execute(f"UPDATE comparisons SET {set_clause} WHERE id = ?", tuple(values))
        self.commit()
        return self.get_comparison(comparison_id)

    def delete_comparison(self, comparison_id: int):
        self.execute("DELETE FROM comparisons WHERE id = ?", (comparison_id,))
        self.commit()


# ── Schema SQL ───────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ai_providers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    base_url TEXT,
    api_key TEXT,
    model TEXT,
    is_default BOOLEAN DEFAULT 0,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mt5_targets (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    install_path TEXT NOT NULL,
    data_path TEXT,
    is_portable BOOLEAN DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS deployments (
    id INTEGER PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    mt5_target_id INTEGER,
    ai_provider_id INTEGER,
    status TEXT NOT NULL,
    sqx_version TEXT,
    deployed_version TEXT,
    errors_found INTEGER DEFAULT 0,
    errors_fixed INTEGER DEFAULT 0,
    ai_review_log TEXT,
    compilation_log TEXT,
    created_at TIMESTAMP,
    FOREIGN KEY (mt5_target_id) REFERENCES mt5_targets(id),
    FOREIGN KEY (ai_provider_id) REFERENCES ai_providers(id)
);

CREATE TABLE IF NOT EXISTS backups (
    id INTEGER PRIMARY KEY,
    deployment_id INTEGER,
    strategy_name TEXT,
    file_path TEXT,
    file_hash TEXT,
    created_at TIMESTAMP,
    FOREIGN KEY (deployment_id) REFERENCES deployments(id)
);

CREATE TABLE IF NOT EXISTS comparisons (
    id INTEGER PRIMARY KEY,
    deployment_id INTEGER,
    sqx_metrics TEXT,
    mt5_metrics TEXT,
    deltas TEXT,
    status TEXT,
    report_path TEXT,
    created_at TIMESTAMP,
    FOREIGN KEY (deployment_id) REFERENCES deployments(id)
);
"""
